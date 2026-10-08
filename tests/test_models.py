"""The Models page's switching logic (ui/models.py), against fake Kubernetes and Ollama APIs."""

import json

import httpx
import pytest

import models


def kube(handler):
    return models.Kube(base="https://k8s", token="t", verify=False, transport=httpx.MockTransport(handler))


def test_choice_defaults_and_falls_back_to_chat():
    assert kube(lambda r: httpx.Response(404)).choice() == {uc: models.DEFAULT_MODEL for uc in models.USE_CASES}
    data = {"model": "qwen3:4b", "agent": "", "email": "llama3.2:1b"}
    assert kube(lambda r: httpx.Response(200, json={"data": data})).choice() == {
        "chat": "qwen3:4b", "agent": "qwen3:4b", "email": "llama3.2:1b"}


def test_set_choice_creates_the_configmap_and_stores_same_as_chat_empty():
    calls, written = [], {}

    def handler(r):
        calls.append(r.method)
        if r.method in ("PUT", "POST"):
            written.update(json.loads(r.content)["data"])
        return httpx.Response(404 if r.method in ("GET", "PUT") else 201)

    kube(handler).set_choice({"chat": "qwen3:4b", "agent": "qwen3:4b", "email": "llama3.2:1b"})
    assert calls == ["GET", "PUT", "POST"]
    assert written == {"model": "qwen3:4b", "agent": "", "email": "llama3.2:1b"}


def test_speeds_are_kept_per_model():
    store = {"data": {"model": "qwen2.5:3b", "speeds": '{"llama3.2:3b": 8.9}'}}

    def handler(r):
        if r.method == "PUT":
            store["data"] = json.loads(r.content)["data"]
        return httpx.Response(200, json=store)

    k = kube(handler)
    k.save_speed("qwen2.5:3b", 8.14)
    assert k.speeds() == {"llama3.2:3b": 8.9, "qwen2.5:3b": 8.1} and store["data"]["model"] == "qwen2.5:3b"


def test_restart_patches_the_pod_template_like_kubectl():
    seen = {}

    def handler(r):
        seen.update(path=r.url.path, kind=r.headers["content-type"], body=json.loads(r.content))
        return httpx.Response(200)

    kube(handler).restart_litellm()
    assert seen["path"] == "/apis/apps/v1/namespaces/llm/deployments/litellm"
    assert seen["kind"] == "application/strategic-merge-patch+json"
    assert "kubectl.kubernetes.io/restartedAt" in seen["body"]["spec"]["template"]["metadata"]["annotations"]


@pytest.mark.parametrize("status, ready", [
    ({"observedGeneration": 5, "updatedReplicas": 1, "availableReplicas": 1}, True),
    ({"observedGeneration": 4, "updatedReplicas": 1, "availableReplicas": 1}, False),  # not seen the restart yet
    ({"observedGeneration": 5, "updatedReplicas": 1, "availableReplicas": 1, "unavailableReplicas": 1}, False),
])
def test_litellm_ready(status, ready):
    body = {"metadata": {"generation": 5}, "spec": {"replicas": 1}, "status": status}
    assert kube(lambda r: httpx.Response(200, json=body)).litellm_ready() is ready


def test_switch_frees_the_old_chat_model_but_keeps_embeddings(monkeypatch):
    done = []

    class FakeKube:
        def set_choice(self, choice):
            done.append(("active", choice["chat"]))

        def restart_litellm(self):
            done.append(("restart",))

    monkeypatch.setattr(models, "in_memory", lambda: {"qwen2.5:3b", "nomic-embed-text:latest", "qwen3:4b"})
    monkeypatch.setattr(models, "unload", lambda m: done.append(("unload", m)))
    assert models.switch(FakeKube(), "qwen3:4b") == ["qwen2.5:3b"]
    assert done == [("active", "qwen3:4b"), ("restart",), ("unload", "qwen2.5:3b")]


@pytest.mark.parametrize("name, ok", [("qwen3:4b", True), ("hf.co/bartowski/Phi-4-mini-GGUF:Q4_K_M", True),
                                      ("", False), ("qwen; rm -rf /", False), ("-x", False)])
def test_model_names(name, ok):
    assert models.valid_name(name) is ok


def test_system_reads_the_vms_memory_and_load():
    info = models.system(meminfo="MemTotal: 18417264 kB\nMemFree: 1 kB\nMemAvailable: 8902228 kB\n",
                         loadavg="2.60 2.62 2.88 4/1325 1", cpus=8)
    assert info == {"total_gb": 18.9, "available_gb": 9.1, "used_gb": 9.7, "cpus": 8, "load": 2.6, "cpu_pct": 32}


def test_expected_ram_errs_high_and_verdicts():
    assert models.expected_ram_gb(1.9) >= 2.4 and models.expected_ram_gb(2.0) >= 3.0  # measured 2.4 and 3.1
    assert models.verdict(2.5, 9.0) == "fits" and models.verdict(8.5, 9.0) == "tight" and models.verdict(9.5, 9.0) == "too big"


def test_speed_is_measured_or_scaled_from_measured_models():
    speeds, sizes = {"qwen2.5:3b": 8.0}, {"qwen2.5:3b": 2.0, "big:7b": 4.0}
    assert models.expected_speed("qwen2.5:3b", 2.0, speeds, sizes) == (8.0, True)
    assert models.expected_speed("big:7b", 4.0, speeds, sizes) == (4.0, False)  # twice the size, half the speed
    assert models.expected_speed("x", 1.0, {}, sizes) == (None, False)


def test_plan_counts_two_models_at_most_and_what_unloading_frees():
    ram = {"a": 3.0, "b": 2.5, "c": 1.0}
    one = models.plan_fit({"chat": "a", "agent": "a", "email": "a"}, ram, {"b": 2.5, "nomic-embed-text:latest": 0.6}, 4.0)
    assert one == {"models": ["a"], "need_gb": 3.0, "free_gb": 6.5, "verdict": "fits", "swaps": False}
    three = models.plan_fit({"chat": "a", "agent": "b", "email": "c"}, ram, {}, 6.0)
    assert three["need_gb"] == 5.5 and three["verdict"] == "tight" and three["swaps"]  # Ollama keeps 2 of the 3

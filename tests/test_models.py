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
    assert kube(lambda r: httpx.Response(200, json={"metadata": {"resourceVersion": "1"}, "data": data})).choice() == {
        "chat": "qwen3:4b", "agent": "qwen3:4b", "email": "llama3.2:1b"}


def test_set_choice_creates_the_configmap_and_stores_same_as_chat_empty():
    calls, written = [], {}

    def handler(r):
        calls.append(r.method)
        if r.method in ("PUT", "POST"):
            written.update(json.loads(r.content)["data"])
        return httpx.Response(404 if r.method == "GET" else 201)

    kube(handler).set_choice({"chat": "qwen3:4b", "agent": "qwen3:4b", "email": "llama3.2:1b"})
    assert calls == ["GET", "POST"]
    assert written == {"model": "qwen3:4b", "agent": "", "email": "llama3.2:1b"}


class Store:
    """A fake ConfigMap with resourceVersion checks, like the API server."""

    def __init__(self, data, conflicts=0):
        self.data, self.version, self.conflicts, self.puts = data, 1, conflicts, 0

    def __call__(self, r):
        if r.method == "GET":
            return httpx.Response(200, json={"metadata": {"resourceVersion": str(self.version)}, "data": self.data})
        body = json.loads(r.content)
        self.puts += 1
        if self.conflicts:  # someone else wrote in between
            self.conflicts -= 1
            self.version += 1
            return httpx.Response(409)
        assert body["metadata"]["resourceVersion"] == str(self.version)
        self.data, self.version = body["data"], self.version + 1
        return httpx.Response(200, json=body)


def test_update_retries_when_someone_else_wrote_in_between():
    store = Store({"model": "qwen2.5:3b"}, conflicts=2)
    kube(store).update(lambda d: d | {"evals": "[]"})
    assert store.puts == 3 and store.data == {"model": "qwen2.5:3b", "evals": "[]"}
    with pytest.raises(RuntimeError, match="kept changing"):
        kube(Store({}, conflicts=9)).update(lambda d: d)


def test_speeds_are_kept_per_model():
    store = Store({"model": "qwen2.5:3b", "speeds": '{"llama3.2:3b": 8.9}'})
    handler = store

    k = kube(handler)
    k.save_speed("qwen2.5:3b", 8.14)
    assert k.speeds() == {"llama3.2:3b": 8.9, "qwen2.5:3b": 8.1} and store.data["model"] == "qwen2.5:3b"


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


# ---- audit trail and rollback (#30) --------------------------------------------------------
ONE = {"chat": "qwen2.5:3b", "agent": "qwen2.5:3b", "email": "qwen2.5:3b"}
TWO = {"chat": "qwen2.5:3b", "agent": "qwen2.5:3b", "email": "llama3.2:3b"}


def test_every_change_is_recorded_with_who_and_kept_to_the_last_50():
    store = Store({"model": "qwen2.5:3b", "history": json.dumps([{"action": "old"}] * 50)})
    k = kube(store)
    e = models.record(k, "apply", "nixon", before=ONE, after=TWO, note="7.8 tok/s")
    log = models.audit_log(k)
    assert len(log) == 50 and log[-1] == e and e["by"] == "nixon" and e["before"] == ONE and e["after"] == TWO
    assert models.record(k, "delete", "", note="x")["by"] == "unknown"


def test_revert_goes_back_to_what_led_to_the_current_models():
    log = [{"action": "apply", "before": TWO, "after": ONE}, {"action": "evaluate", "after": ONE},
           {"action": "apply", "before": ONE, "after": TWO}]
    assert models.previous(log, TWO) == ONE
    assert models.previous(log + [{"action": "revert", "before": TWO, "after": ONE}], ONE) == TWO  # undo the undo
    assert models.previous(log, {"chat": "other", "agent": "other", "email": "other"}) is None
    assert models.summary(ONE) == "qwen2.5:3b everywhere"
    assert models.summary(TWO) == "chat qwen2.5:3b · agent qwen2.5:3b · email llama3.2:3b"

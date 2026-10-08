"""The Models page's switching logic (ui/models.py), against fake Kubernetes and Ollama APIs."""

import json

import httpx
import pytest

import models


def kube(handler):
    return models.Kube(base="https://k8s", token="t", verify=False, transport=httpx.MockTransport(handler))


def test_active_model_defaults_until_one_is_chosen():
    assert kube(lambda r: httpx.Response(404)).active() == models.DEFAULT_MODEL
    assert kube(lambda r: httpx.Response(200, json={"data": {"model": "qwen3:4b"}})).active() == "qwen3:4b"


def test_set_active_creates_the_configmap_the_first_time():
    calls = []

    def handler(r):
        calls.append((r.method, r.url.path))
        return httpx.Response(404 if r.method == "PUT" else 201)

    kube(handler).set_active("qwen3:4b")
    assert calls == [("PUT", "/api/v1/namespaces/llm/configmaps/llm-model"), ("POST", "/api/v1/namespaces/llm/configmaps")]


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
        def set_active(self, name):
            done.append(("active", name))

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

"""Model switching for the agent UI's Models page (README §6.9): one chat model at a time.

Ollama (on the WSL host) keeps the downloaded models; LiteLLM maps the chat aliases
(chat-default, chat-tools) to the ACTIVE one, named in ConfigMap llm/llm-model. Switching
writes that ConfigMap, restarts LiteLLM (it reads the name on start) and unloads the previous
model from RAM. The embedding model (document search) is separate and always stays.

Kubernetes access: the ui/agent-ui ServiceAccount may read/write that one ConfigMap and
restart the litellm Deployment, nothing else (ui/agent-ui.yaml).
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama.llm.svc.cluster.local:11434")
LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm.llm.svc.cluster.local:4000")
K8S_URL = "https://kubernetes.default.svc"
SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
NS, CONFIGMAP, DEPLOYMENT = "llm", "llm-model", "litellm"
DEFAULT_MODEL = "qwen2.5:3b"  # what LiteLLM uses until a model is chosen (llm/litellm.yaml)
EMBED_PREFIX = "nomic-embed-text"  # the document-search embeddings; never switched or deleted here
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,120}$")

# Small models that run on this CPU-only laptop (README §6.9); any Ollama name works
SUGGESTED = {
    "qwen3:4b": "newer Qwen, better tool calling (~2.6 GB)",
    "gemma3:4b": "strong general chat; check the Tool calling column (~3.3 GB)",
    "phi4-mini": "reasoning and maths (~2.5 GB)",
    "llama3.2:1b": "very fast, simple answers (~1.3 GB)",
    "qwen2.5-coder:3b": "code questions (~1.9 GB)",
}


class Kube:
    """The few Kubernetes API calls the page needs, with the pod's ServiceAccount token."""

    def __init__(self, base: str = K8S_URL, token: str | None = None, verify=None, transport=None):
        token = token if token is not None else (SA / "token").read_text()
        verify = verify if verify is not None else str(SA / "ca.crt")
        self.client = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"},
                                   verify=verify, timeout=15, transport=transport)

    def active(self) -> str:
        r = self.client.get(f"/api/v1/namespaces/{NS}/configmaps/{CONFIGMAP}")
        if r.status_code == 404:
            return DEFAULT_MODEL
        r.raise_for_status()
        return r.json().get("data", {}).get("model") or DEFAULT_MODEL

    def set_active(self, model: str) -> None:
        body = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": CONFIGMAP, "namespace": NS},
                "data": {"model": model}}
        r = self.client.put(f"/api/v1/namespaces/{NS}/configmaps/{CONFIGMAP}", json=body)
        if r.status_code == 404:
            r = self.client.post(f"/api/v1/namespaces/{NS}/configmaps", json=body)
        r.raise_for_status()

    def restart_litellm(self) -> None:
        """What `kubectl rollout restart` does: a new pod-template annotation."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        patch = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}}
        r = self.client.patch(f"/apis/apps/v1/namespaces/{NS}/deployments/{DEPLOYMENT}", content=json.dumps(patch),
                              headers={"Content-Type": "application/strategic-merge-patch+json"})
        r.raise_for_status()

    def litellm_ready(self) -> bool:
        d = self.client.get(f"/apis/apps/v1/namespaces/{NS}/deployments/{DEPLOYMENT}").json()
        st, want = d.get("status", {}), d["spec"].get("replicas", 1)
        return (st.get("observedGeneration", 0) >= d["metadata"]["generation"] and st.get("updatedReplicas") == want
                and st.get("availableReplicas") == want and not st.get("unavailableReplicas"))


def valid_name(name: str) -> bool:
    return bool(NAME.match(name.strip()))


def is_embedding(name: str) -> bool:
    return name.startswith(EMBED_PREFIX)


def installed() -> list[dict]:
    """Downloaded models: name, size (GB), parameters, quantization."""
    r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=15)
    r.raise_for_status()
    return sorted(
        ({"name": m["name"], "gb": round(m.get("size", 0) / 1e9, 1),
          "params": m.get("details", {}).get("parameter_size", ""),
          "quant": m.get("details", {}).get("quantization_level", "")} for m in r.json().get("models", [])),
        key=lambda m: m["name"],
    )


def in_memory() -> set[str]:
    r = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=15)
    r.raise_for_status()
    return {m["name"] for m in r.json().get("models", [])}


def capabilities(name: str) -> list[str]:
    r = httpx.post(f"{OLLAMA_URL}/api/show", json={"model": name}, timeout=30)
    r.raise_for_status()
    return r.json().get("capabilities", [])


def pull(name: str):
    """Download a model; yields (status, fraction or None) as Ollama reports progress."""
    with httpx.stream("POST", f"{OLLAMA_URL}/api/pull", json={"model": name, "stream": True}, timeout=None) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            msg = json.loads(line)
            if "error" in msg:
                raise RuntimeError(msg["error"])
            total, done = msg.get("total"), msg.get("completed")
            yield msg.get("status", ""), (done / total if total and done is not None else None)


def unload(name: str) -> None:
    httpx.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=60)


def delete(name: str) -> None:
    r = httpx.request("DELETE", f"{OLLAMA_URL}/api/delete", json={"model": name}, timeout=60)
    r.raise_for_status()


def switch(kube: Kube, name: str) -> list[str]:
    """Make `name` the active chat model; returns the models unloaded from RAM."""
    kube.set_active(name)
    kube.restart_litellm()
    freed = [m for m in in_memory() if m != name and not is_embedding(m)]
    for m in freed:
        unload(m)
    return freed


def smoke_test() -> tuple[str, float]:
    """One short answer through LiteLLM (loads the model): (reply, seconds)."""
    start = datetime.now()
    r = httpx.post(f"{LITELLM_URL}/v1/chat/completions", headers={"Authorization": "Bearer sk-local"}, timeout=600,
                   json={"model": "chat-default", "messages": [{"role": "user", "content": "Reply with the single word OK."}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip(), round((datetime.now() - start).total_seconds(), 1)

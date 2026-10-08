"""Model choice for the agent UI's Models page (README §6.9): which model each use case runs,
and whether it fits this laptop.

Ollama (on the WSL host) keeps the downloaded models; LiteLLM maps each use case's alias to the
model chosen for it, read from ConfigMap llm/llm-model on start:
    chat   -> chat-default  (Open WebUI)                         key "model"
    agent  -> chat-tools    (the agent: briefing, voice, web...) key "agent" ("" = same as chat)
    email  -> chat-email    (n8n's e-mail triage)                key "email" ("" = same as chat)
Applying a choice writes that ConfigMap, restarts LiteLLM and unloads chat models no use case
needs any more. Ollama keeps at most 2 models in RAM (03-ollama-config.sh), so different models
per use case swap rather than pile up. The embedding model (document search) is separate.

Fit and speed: RAM comes from /proc/meminfo (a pod sees the WSL VM's memory, which is where
Ollama runs). A loaded model's RAM is what Ollama reports; otherwise it's estimated from the
file size plus the 8K context. Speed is measured once per model (tokens/s, stored in the
ConfigMap) and estimated from the measured ones until then: on a CPU it scales with model size.

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
NUM_CTX = 8192  # same as litellm.yaml, so the speed test doesn't reload the model
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,120}$")
HEADROOM_GB = 1.0  # left free for everything else; below it a model is "tight"
ANSWER_TOKENS = 150  # a short answer, for "~N s per answer"

# use case -> (label, ConfigMap key, LiteLLM alias, needs tool calling)
USE_CASES = {
    "chat": ("Chat (Open WebUI)", "model", "chat-default", False),
    "agent": ("Agent: files, calendar, web, briefing, voice", "agent", "chat-tools", True),
    "email": ("E-mail triage (n8n)", "email", "chat-email", False),
}

# Small models for this CPU-only laptop (README §6.9), with their download size; any Ollama name works
SUGGESTED = {
    "qwen3:4b": ("newer Qwen, better tool calling", 2.6),
    "gemma3:4b": ("strong general chat", 3.3),
    "phi4-mini": ("reasoning and maths", 2.5),
    "llama3.2:1b": ("very fast, simple answers", 1.3),
    "qwen2.5-coder:3b": ("code questions", 1.9),
}


class Kube:
    """The few Kubernetes API calls the page needs, with the pod's ServiceAccount token."""

    def __init__(self, base: str = K8S_URL, token: str | None = None, verify=None, transport=None):
        token = token if token is not None else (SA / "token").read_text()
        verify = verify if verify is not None else str(SA / "ca.crt")
        self.client = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"},
                                   verify=verify, timeout=15, transport=transport)

    def _data(self) -> dict:
        r = self.client.get(f"/api/v1/namespaces/{NS}/configmaps/{CONFIGMAP}")
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json().get("data") or {}

    def _write(self, data: dict) -> None:
        body = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": CONFIGMAP, "namespace": NS}, "data": data}
        r = self.client.put(f"/api/v1/namespaces/{NS}/configmaps/{CONFIGMAP}", json=body)
        if r.status_code == 404:
            r = self.client.post(f"/api/v1/namespaces/{NS}/configmaps", json=body)
        r.raise_for_status()

    def choice(self) -> dict[str, str]:
        """The model of each use case; agent and e-mail fall back to chat's."""
        data = self._data()
        chat = data.get("model") or DEFAULT_MODEL
        return {uc: (data.get(key) or chat) for uc, (_, key, _, _) in USE_CASES.items()} | {"chat": chat}

    def active(self) -> str:
        return self.choice()["chat"]

    def set_choice(self, choice: dict[str, str]) -> None:
        data = self._data()
        for uc, (_, key, _, _) in USE_CASES.items():
            if uc in choice:
                # agent/e-mail equal to chat are stored as "", so they follow chat's next change
                data[key] = choice[uc] if uc == "chat" or choice[uc] != choice.get("chat", data.get("model")) else ""
        self._write(data)

    def set_active(self, model: str) -> None:
        """Every use case on one model."""
        self.set_choice({uc: model for uc in USE_CASES})

    def speeds(self) -> dict[str, float]:
        try:
            return json.loads(self._data().get("speeds") or "{}")
        except ValueError:
            return {}

    def save_speed(self, model: str, tps: float) -> None:
        data = self._data()
        speeds = json.loads(data.get("speeds") or "{}")
        speeds[model] = round(tps, 1)
        data["speeds"] = json.dumps(speeds, sort_keys=True)
        self._write(data)

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


# ---- the laptop ----------------------------------------------------------------------------
def system(meminfo: str | None = None, loadavg: str | None = None, cpus: int | None = None) -> dict:
    """RAM (GB) and CPU load of the WSL VM: a pod's /proc shows the host's numbers."""
    meminfo = meminfo if meminfo is not None else Path("/proc/meminfo").read_text()
    loadavg = loadavg if loadavg is not None else Path("/proc/loadavg").read_text()
    kb = {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in meminfo.splitlines() if ":" in line)}
    total, avail = kb["MemTotal"] / 1e6 * 1.024, kb["MemAvailable"] / 1e6 * 1.024
    cpus = cpus or os.cpu_count() or 1
    load1 = float(loadavg.split()[0])
    return {"total_gb": round(total, 1), "available_gb": round(avail, 1), "used_gb": round(total - avail, 1),
            "cpus": cpus, "load": round(load1, 1), "cpu_pct": min(100, round(100 * load1 / cpus))}


def expected_ram_gb(file_gb: float) -> float:
    """RAM a model takes once loaded with the 8K context: weights plus KV cache and buffers.
    Measured here (2026-10-08): llama3.2:3b 2.0 GB file -> 3.1 GB loaded; qwen2.5:3b 1.9 -> 2.4 GB.
    The KV cache differs per architecture, so this errs on the high side."""
    return round(file_gb * 1.35 + 0.3, 1)


def verdict(need_gb: float, free_gb: float) -> str:
    if need_gb <= free_gb - HEADROOM_GB:
        return "fits"
    return "tight" if need_gb <= free_gb else "too big"


ICON = {"fits": "✅", "tight": "⚠️", "too big": "❌"}


def expected_speed(model: str, file_gb: float, speeds: dict[str, float], sizes: dict[str, float]) -> tuple[float | None, bool]:
    """(tokens/s, measured?). Unmeasured: on a CPU, speed x size is roughly constant (memory
    bandwidth), so scale from the models measured so far."""
    if model in speeds:
        return speeds[model], True
    known = [speeds[m] * sizes[m] for m in speeds if sizes.get(m)]
    if not known or not file_gb:
        return None, False
    return round(sum(known) / len(known) / file_gb, 1), False


def plan_fit(choice: dict[str, str], ram: dict[str, float], loaded: dict[str, float], available_gb: float) -> dict:
    """Will these models run? Ollama keeps at most 2 in RAM, so up to two distinct chat models
    may be loaded together. Free RAM counts what unloading the current chat models gives back."""
    distinct = sorted(set(choice.values()))
    freed = sum(gb for m, gb in loaded.items() if not is_embedding(m))
    free = available_gb + freed
    together = sorted((ram.get(m, 0) for m in distinct), reverse=True)[:2]
    need = round(sum(together), 1)
    return {"models": distinct, "need_gb": need, "free_gb": round(free, 1), "verdict": verdict(need, free),
            "swaps": len(distinct) > 1}


# ---- Ollama --------------------------------------------------------------------------------
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


def in_memory() -> dict[str, float]:
    """Models in RAM now, with the GB each takes (weights + context)."""
    r = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=15)
    r.raise_for_status()
    return {m["name"]: round(m.get("size", 0) / 1e9, 1) for m in r.json().get("models", [])}


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


def apply(kube: Kube, choice: dict[str, str]) -> list[str]:
    """Give each use case its model; returns the chat models unloaded from RAM."""
    kube.set_choice(choice)
    kube.restart_litellm()
    keep = set(choice.values())
    freed = [m for m in in_memory() if m not in keep and not is_embedding(m)]
    for m in freed:
        unload(m)
    return freed


def switch(kube: Kube, name: str) -> list[str]:
    """Every use case on `name`; returns the models unloaded from RAM."""
    return apply(kube, {uc: name for uc in USE_CASES})


def speed_test(model: str) -> tuple[float, float]:
    """Load the model (if needed) and generate a short answer: (tokens/s, seconds in total)."""
    r = httpx.post(f"{OLLAMA_URL}/api/generate", timeout=600, json={
        "model": model, "stream": False, "prompt": "In two sentences, why is the sky blue?",
        "options": {"num_ctx": NUM_CTX, "num_predict": 64, "temperature": 0}})
    r.raise_for_status()
    d = r.json()
    return round(d["eval_count"] / (d["eval_duration"] / 1e9), 1), round(d["total_duration"] / 1e9, 1)


def smoke_test(alias: str = "chat-default") -> tuple[str, float]:
    """One short answer through LiteLLM (loads the model): (reply, seconds)."""
    start = datetime.now()
    r = httpx.post(f"{LITELLM_URL}/v1/chat/completions", headers={"Authorization": "Bearer sk-local"}, timeout=600,
                   json={"model": alias, "messages": [{"role": "user", "content": "Reply with the single word OK."}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip(), round((datetime.now() - start).total_seconds(), 1)

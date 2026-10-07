# Week 1: k3s, Ollama, Qdrant, Open WebUI, LiteLLM

**Deliverable:** chat works, locally, on CPU. ✅

## What runs
- k3s inside WSL2 (Ubuntu 26.04), Traefik on the WSL host's ports 80/443.
- Ollama as a systemd service on the WSL host (not in k3s), models `llama3.2:3b`, `qwen2.5:3b`,
  `nomic-embed-text`; pods reach it through the Service `llm/ollama`.
- LiteLLM gateway: clients ask for aliases (`chat-default`, `chat-tools`, `embed-default`), never
  for Ollama model names, so switching a model is one ConfigMap edit.
- Qdrant (vectors), Open WebUI (chat, https://chat.ai.local).

## Decisions
- **Ollama on the host, not in k3s:** direct access to all CPU threads and RAM, models survive
  cluster rebuilds; the trade-off is that GitOps doesn't manage it (its settings live in
  `03-ollama-config.sh`).
- **Services start on demand** (`.\local-up` / `.\local-down`), so Ubuntu costs nothing idle.
- **Hosts entries point at `::1`**, one name per line: WSL forwards only IPv6 localhost, and
  Windows ignores extra names on a `::1` line.
- **Images pinned by tag + digest** (LiteLLM v1.103.1, later Headlamp, Postgres, SeaweedFS,
  Authelia), upgraded deliberately.
- Open WebUI is configured from env vars on every start (`ENABLE_PERSISTENT_CONFIG=false`), so
  the manifest is the truth, not the admin panel.

## Measured
- WSL memory cap 18 GB (Windows needs 8–15 GB); chat via LiteLLM answers "OK" in ~0.3 s once the
  model is loaded, embeddings (768 dims) in ~1.6 s.

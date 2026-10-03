# Local AI Platform

A self-hosted, MCP-based AI agent platform running on **k3s inside WSL2 (Ubuntu 26.04)** on a single laptop, with no cloud spend and no GPU.

| | |
|---|---|
| **Core stack** | Ollama (3B models) · LiteLLM · LangGraph · MCP · Qdrant · MLflow · Dagster · BentoML · n8n · Langfuse · ArgoCD |
| **Hardware** | Windows 11 laptop, 8+ CPU threads, 32 GB RAM, ~100 GB free SSD (reference build: Intel Core i7-9850H, 6 cores / 12 threads) |
| **Cost** | $0 (all open source + GitHub free tier) |
| **GPU** | Not required: everything runs on the CPU (small laptop GPUs with 2–4 GB VRAM don't help 3B models) |
| **Timeline** | 8 weeks, part-time |
| **License** | [MIT](LICENSE) |

---

## Table of Contents

1. [Goals](#1-goals)
2. [Technology Stack](#2-technology-stack)
3. [Architecture](#3-architecture)
4. [Repository Structure](#4-repository-structure)
5. [Prerequisites](#5-prerequisites)
6. [Installation](#6-installation)
7. [CI/CD and GitOps](#7-cicd-and-gitops)
8. [Resource Budget](#8-resource-budget)
9. [Workflows (Functional Requirements)](#9-workflows-functional-requirements)
10. [UI Access](#10-ui-access)
11. [Non-Functional Requirements](#11-non-functional-requirements)
12. [Thermal Management](#12-thermal-management)
13. [8-Week Build Plan](#13-8-week-build-plan)
14. [Key Decisions](#14-key-decisions)
15. [Open Issues and Risks](#15-open-issues-and-risks)
16. [Deliverables](#16-deliverables)

---

## 1. Goals

- Run a complete AI agent platform locally, privately, and for free.
- Use **MCP (Model Context Protocol)** as the standard tool interface for the agent.
- Combine **LLM/RAG** workloads with **classical ML** (training, tuning, serving, drift detection).
- Operate it like production: GitOps deployment, CI/CD, tracing, metrics, dashboards.
- Deliver **10 working end-to-end workflows** and a portfolio-quality monorepo.

---

## 2. Technology Stack

| Layer | Tool | Purpose |
|---|---|---|
| Runtime | k3s (in WSL2) | Lightweight Kubernetes |
| Ingress | Traefik (bundled with k3s) | Host-based routing to `*.local` UIs |
| LLM | Ollama: `llama3.2:3b`, `qwen2.5:3b`, `phi3:mini` | CPU inference |
| Embeddings | `nomic-embed-text` (via Ollama) | Vector embeddings for RAG |
| LLM gateway | LiteLLM | One OpenAI-compatible API and model aliases for every backend |
| Agent | LangGraph | Stateful agent graph / orchestration |
| Protocol | MCP | Standard tool interface between agent and tools |
| Vector DB | Qdrant | Embedding storage and similarity search |
| Database | Postgres / SQLite | App state, metadata, backends for MLflow/n8n/Langfuse |
| Object Storage | MinIO | S3-compatible artifact and document storage |
| ML Tracking | MLflow | Experiments, metrics, model registry |
| Pipelines | Dagster | Training, tuning, and RAG indexing pipelines |
| Serving | BentoML | Serve trained models as APIs (exposed to agent as a tool) |
| Tuning | Optuna | Hyperparameter optimisation |
| Drift | Evidently | Data / model drift reports |
| UI | Open WebUI + custom Streamlit | Chat UI and agent UI |
| Cluster UI | Headlamp | Web dashboard for pods, logs, events and resource usage |
| Automation | n8n | Scheduled and event-driven workflows |
| LLM Observability | Langfuse | Prompt/response traces, latency, cost |
| Metrics | Prometheus + Grafana | Cluster and service metrics |
| GitOps | ArgoCD | Sync manifests from GitHub to k3s |
| CI/CD | GitHub Actions + GHCR | Test, build, and publish container images |

### MCP Servers

| Server | Capability |
|---|---|
| `filesystem` | Read/search/list local files |
| `web-search` | Search the web |
| `fetch` | Fetch and extract web page content |
| `memory` | Long-term conversational memory |
| `sqlite` | Query structured data |
| `time` | Current time, timezone and date calculations |

---

## 3. Architecture

```text
Windows 11 (32 GB) ── browser ──► http://*.local (hosts file → ::1 → WSL)
   └── WSL2 (18 GB RAM, 8 cores)
         └── Ubuntu 26.04 (systemd enabled; services start on demand, see 6.6)
               ├── Ollama (systemd service on the WSL host, :11434)
               ├── Docker Engine (image builds / compose only, own image store)
               └── k3s
                     ├── kube-system:   Traefik on host ports 80/443, CoreDNS, local-path storage
                     ├── llm:           LiteLLM gateway (:4000) + Service "ollama" → Ollama on the host
                     ├── storage:       Qdrant, MinIO, Postgres
                     ├── mlops:         MLflow, Dagster, BentoML
                     ├── agent:         LangGraph + MCP servers
                     ├── ui:            Open WebUI + Streamlit
                     ├── automation:    n8n
                     ├── observability: Langfuse, Grafana, Prometheus
                     └── argocd
```

### Request flow (agent)

```text
User ──► Open WebUI / Streamlit ──► Traefik ──► LangGraph agent
                                                   │
                     ┌─────────────────────────────┼──────────────────────────┐
                     ▼                             ▼                          ▼
             LiteLLM (gateway)             MCP servers (tools)        BentoML (ML model)
                     │                             │
                     ▼                             ▼
          Ollama (LLM + embeddings)     filesystem / web / memory / sqlite / time
          Qdrant (RAG retrieval)

All LLM calls (via LiteLLM) ──► Langfuse (traces)     All pods ──► Prometheus ──► Grafana
```

---

## 4. Repository Structure

```text
local-ai-platform/
├── README.md
├── LICENSE                 # MIT
├── local-up.ps1            # .\local-up: start the platform from Windows (wraps platform.ps1 up)
├── local-down.ps1          # .\local-down: stop it and shut Ubuntu down (wraps platform.ps1 down)
├── Makefile                # make up / down / status / deploy / llm-reload (inside Ubuntu)
├── .gitignore              # also keeps machine-specific files (SYSTEM_*.md, DEVICE_LOG.md) local
├── .github/workflows/
│   ├── ci.yml              # lint + tests
│   ├── build.yml           # build images, push to GHCR, bump manifests
│   └── cleanup.yml         # prune old GHCR images (stay under 500 MB)
├── infra/
│   ├── k3s/
│   │   ├── namespaces.yaml
│   │   ├── limits.yaml     # default requests/limits per namespace
│   │   ├── llm/ollama-host.yaml  # in-cluster Service for the host's Ollama
│   │   ├── llm/litellm.yaml      # LLM gateway: model aliases (edit to switch/add models)
│   │   ├── storage/qdrant.yaml
│   │   ├── storage/minio.yaml
│   │   ├── storage/postgres.yaml
│   │   ├── mlops/mlflow.yaml
│   │   ├── mlops/dagster.yaml
│   │   ├── mlops/bentoml.yaml
│   │   ├── agent/agent.yaml      # file agent API + filesystem MCP server
│   │   ├── ui/open-webui.yaml
│   │   ├── ui/agent-ui.yaml      # Streamlit agent UI (agent.local)
│   │   ├── ui/headlamp.yaml      # Kubernetes dashboard (headlamp.local)
│   │   ├── automation/n8n.yaml
│   │   ├── observability/langfuse.yaml
│   │   ├── ingress/ingresses.yaml
│   │   └── ingress/traefik-config.yaml
│   ├── argocd/
│   │   ├── install.sh
│   │   └── app.yaml
│   └── scripts/
│       ├── host/           # one-time machine setup, numbered in run order (see 6.x)
│       │   ├── 00-assess.ps1 (+ assess-wsl.sh)  # read-only readiness report
│       │   ├── 01-install-k3s-helm-ollama.sh
│       │   ├── 02-pull-models.sh
│       │   ├── 03-ollama-config.sh
│       │   ├── 04-install-docker.sh
│       │   ├── 05-on-demand-services.sh
│       │   ├── windows-wsl-idle.ps1
│       │   ├── windows-hosts.ps1    # *.local → ::1 in the hosts file (admin)
│       │   └── windows-thermal.ps1
│       ├── platform.ps1    # up / down / status from Windows
│       ├── platform.sh     # up / down / status inside Ubuntu
│       ├── deploy.sh
│       ├── build-images.sh # build our images, load them into k3s (make images)
│       ├── teardown.sh     # delete all workloads and their volumes
│       └── status.sh
├── agent/                  # LangGraph agent (6.10)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py             # FastAPI: POST /chat, GET /tools
│   ├── graph.py            # model -> tools loop; tools come from MCP servers
│   └── prompts/system.md
├── mcp-servers/
│   ├── filesystem/         # read-only list/search/read over one folder (6.10)
│   ├── web-search/
│   ├── fetch/
│   ├── memory/
│   ├── sqlite/
│   └── time/
├── pipelines/
│   ├── train.py
│   ├── tune.py
│   ├── rag_index.py
│   └── dagster_job.py
├── serving/
│   └── service.py
├── n8n/workflows/
├── ui/                     # Streamlit agent UI
├── data/
├── tests/                  # pytest, no cluster or LLM needed (make test)
├── docs/
└── docker-compose.yml      # optional: run the agent stack without k3s for fast local dev
```

---

## 5. Prerequisites

### Hardware
- x86-64 CPU with 8+ threads (e.g. Intel Core i7) and virtualization (VT-x / AMD-V) on
- 32 GB RAM
- ~100 GB free SSD space (models, images, volumes)
- Cooling stand recommended (see [Thermal Management](#12-thermal-management))

### Software
- Windows 11 with WSL2 and hardware virtualization enabled
- Ubuntu 26.04 (WSL distro) with systemd enabled
- Git, curl, zstd, make
- k3s (bundles `kubectl`), Helm 3, Ollama, Docker Engine (for image builds)
- A GitHub account (Actions + GHCR free tier)

Not sure your machine qualifies? Run the assessment in [6.0](#60-get-the-repo-and-assess-your-machine); it checks all of the above.

---

## 6. Installation

Every step has a script under [`infra/scripts/host/`](infra/scripts/host/), numbered in run order and safe to re-run. The manual commands are shown for reference.

Two ways to run a Linux script from Windows PowerShell (repo on `D:`, `E:`, … is reachable in Ubuntu under `/mnt/<drive>/...`):

```powershell
wsl -u root -- bash /mnt/e/Github/local-ai-platform/infra/scripts/host/01-install-k3s-helm-ollama.sh   # as root
wsl -- bash /mnt/e/Github/local-ai-platform/infra/scripts/host/02-pull-models.sh                      # as your user
```

Keep a local, git-ignored `docs/DEVICE_LOG.md` of what you ran and how to undo it.

### 6.0 Get the repo and assess your machine

Clone on Windows, on the drive you'll use for WSL (the one with the most free space):

```powershell
git clone https://github.com/nixvarghese01/local-ai-platform E:\Github\local-ai-platform
cd E:\Github\local-ai-platform
.\infra\scripts\host\00-assess.ps1
```

[`00-assess.ps1`](infra/scripts/host/00-assess.ps1) is read-only. It checks CPU, RAM, virtualization, free space, WSL, the distro, `.wslconfig`, systemd, tools and models, suggests `memory=` / `processors=` values for this machine, and writes **`SYSTEM_ASSESSMENT.md`** (git-ignored) with a ✅ / ⚠️ / ❌ / ⬜ list and the next step for each gap. Re-run it after every step below.

### 6.1 WSL2 setup

Install Ubuntu straight onto the drive with the most space (keeps the system drive free), from PowerShell:

```powershell
wsl --install Ubuntu-26.04 --location E:\wsl\Ubuntu-26.04
```

`%UserProfile%\.wslconfig` (Windows side). Take `memory` and `processors` from the assessment:

```ini
[wsl2]
# RAM − what Windows uses − 2 GB, at most 24 GB
memory=18GB
# leave ~4 threads for Windows
processors=8
swap=8GB
# keep swap on the WSL drive (default is %TEMP% on C:)
swapFile=E:\\wsl\\swap.vhdx
localhostForwarding=true
# never auto-stop the VM (windows-wsl-idle.ps1 sets both, see 6.6)
vmIdleTimeout=-1

[general]
instanceIdleTimeout=-1
```

`/etc/wsl.conf` (inside Ubuntu):

```ini
[boot]
systemd=true

[network]
generateResolvConf=true

[user]
default=<name>
```

Apply with `wsl --shutdown` from PowerShell, then reopen Ubuntu.

On the reference machine Windows uses ~8–15 GB with normal apps open, so the WSL cap is 18 GB, not the 24 GB first planned: 24 + 15 would overcommit 32 GB. See [Resource Budget](#8-resource-budget).

### 6.2 Install k3s, Helm and Ollama

Script: [`01-install-k3s-helm-ollama.sh`](infra/scripts/host/01-install-k3s-helm-ollama.sh) (root). Manual equivalent:

```bash
sudo apt-get update && sudo apt-get install -y curl git zstd   # the Ollama installer needs zstd
curl -sfL https://get.k3s.io | sh -
mkdir -p ~/.kube
sudo install -m 600 -o $USER /etc/rancher/k3s/k3s.yaml ~/.kube/config
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
export KUBECONFIG=~/.kube/config
kubectl get nodes
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
curl -fsSL https://ollama.com/install.sh | sh
```

k3s runs as the `k3s` systemd service and ships `kubectl`, Traefik and the `local-path` StorageClass. The installer's "iptables tools not found" notice is harmless; k3s bundles its own.

### 6.3 Models and Ollama settings

Scripts: [`02-pull-models.sh`](infra/scripts/host/02-pull-models.sh) (your user) pulls `llama3.2:3b` and `nomic-embed-text` (~2.3 GB), plus any models you pass it (`02-pull-models.sh qwen2.5:3b phi3:mini`); [`03-ollama-config.sh`](infra/scripts/host/03-ollama-config.sh) (root) writes the systemd override:

```ini
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"   # pods can't reach the default 127.0.0.1
Environment="OLLAMA_NUM_PARALLEL=1"       # one request at a time (heat, RAM)
CPUQuota=400%                             # at most 4 cores' worth of CPU
```

Ollama runs on the **WSL host**, not inside k3s (see [Key Decisions](#14-key-decisions)). Apps don't call it directly: they go through the LiteLLM gateway ([6.9](#69-llm-gateway-litellm-switching-and-adding-models)). LiteLLM reaches it as `http://ollama.llm.svc.cluster.local:11434`: [`llm/ollama-host.yaml`](infra/k3s/llm/ollama-host.yaml) is a Service pointed at `10.42.0.1`, the host's fixed address on k3s's pod network. With WSL's default NAT networking the host is reachable only from this PC, not the LAN.

### 6.4 Install Docker Engine

Script: [`04-install-docker.sh`](infra/scripts/host/04-install-docker.sh) (root). Installs Docker Engine, Compose and Buildx from Docker's apt repo inside Ubuntu (not Docker Desktop) and adds your user to the `docker` group. Docker is only for building images and `docker-compose.yml`; k3s has its own container runtime and image store, so push images to GHCR or load them with `k3s ctr images import`.

### 6.5 Deploy the platform

Inside Ubuntu, from the repo (`cd /mnt/e/Github/local-ai-platform`):

```bash
make images        # = bash infra/scripts/build-images.sh: build the agent, MCP and UI images (first time, and after code changes)
make deploy        # = bash infra/scripts/deploy.sh
```

This applies `infra/k3s/namespaces.yaml`, then everything under `infra/k3s/` (`kubectl apply -R -f infra/k3s/`), and waits for LiteLLM, Qdrant and Open WebUI.

To start over, `make teardown` ([`teardown.sh`](infra/scripts/teardown.sh)) deletes every workload **and its volumes** (Open WebUI accounts and chats, Qdrant vectors). It asks first. k3s, Ollama and the models stay installed.

### 6.6 Start and stop the platform

After [`05-on-demand-services.sh`](infra/scripts/host/05-on-demand-services.sh) (root), k3s, Ollama and Docker do **not** start with Ubuntu, so opening a `wsl` shell costs no CPU or RAM. Start the platform when you need it:

| From Windows (PowerShell, repo folder) | Inside Ubuntu (repo folder) | What it does |
|---|---|---|
| `.\local-up` (or `.\infra\scripts\platform.ps1 up`) | `make local-up` / `make up` | Start Ollama + k3s, replace the previous run's pods with fresh ones, wait until every pod is Ready, print URLs |
| `.\local-up -Docker` | `make up-docker` | Same, plus Docker (the first `docker` command also starts it by itself) |
| `.\local-down` (or `.\infra\scripts\platform.ps1 down`) | `make local-down` / `make down` | Stop all pods cleanly (`k3s-killall.sh`), then k3s, Ollama, Docker. From Windows it also shuts Ubuntu down to free its RAM (skip with `-KeepWsl`; this closes open Ubuntu terminals) |
| `.\infra\scripts\platform.ps1 restart` | `make restart` | `down` then `up` in one go. From Windows Ubuntu is shut down in between too (skip with `-KeepWsl`), so it's a full cold restart with fresh pods |
| `.\infra\scripts\platform.ps1 status` | `make status` | Health check: services, pods since this start, models, LiteLLM chat + embedding, Qdrant, ingress |

Scripts only start and stop services; what runs inside k3s comes from the manifests. Run [`windows-wsl-idle.ps1`](infra/scripts/host/windows-wsl-idle.ps1) once (then `wsl --shutdown`): without `instanceIdleTimeout=-1` / `vmIdleTimeout=-1`, WSL shuts Ubuntu down ~30 s after the last terminal closes, taking k3s with it.

> **Every `up` starts fresh pods.** k3s would otherwise revive the previous run's pods, so `RESTARTS` and `AGE` would pile up across every `down`/`up`. `up` deletes them once the node is Ready and their Deployments create new ones (`RESTARTS 0`). Data on volumes (Open WebUI chats and accounts, Qdrant vectors) and the Ollama models are kept; only [`teardown`](infra/scripts/teardown.sh) deletes those. A `RESTARTS` count above 0 now means a real crash during this run.

### 6.7 Local DNS for `*.local` hostnames

Script: [`windows-hosts.ps1`](infra/scripts/host/windows-hosts.ps1) (admin PowerShell, from the repo folder). It backs up the hosts file, adds the lines below between `# BEGIN/END local-ai-platform` markers, and is safe to re-run; `-Remove` takes them out again. Manual equivalent, in `C:\Windows\System32\drivers\etc\hosts` (as admin):

```text
::1 chat.local
::1 llm.local
::1 agent.local
::1 mlflow.local
::1 dagster.local
::1 n8n.local
::1 langfuse.local
::1 grafana.local
::1 minio.local
::1 qdrant.local
::1 argocd.local
::1 headlamp.local
```

One name per line: Windows treats extra names on a line as aliases of the first, and those don't resolve for `::1`.

Use `::1`, not `127.0.0.1`. Traefik runs on the WSL host's ports 80/443 ([traefik-config.yaml](infra/k3s/ingress/traefik-config.yaml)), and WSL forwards those to Windows' IPv6 localhost only. `http://localhost/` works for the same reason.

### 6.8 Thermal settings (optional)

See [Thermal Management](#12-thermal-management). [`windows-thermal.ps1`](infra/scripts/host/windows-thermal.ps1) caps the CPU at 80%; the Ollama cap is part of 6.3.


### 6.9 LLM gateway (LiteLLM): switching and adding models

[`llm/litellm.yaml`](infra/k3s/llm/litellm.yaml) runs [LiteLLM](https://docs.litellm.ai/) as an OpenAI-compatible gateway at `http://litellm.llm.svc.cluster.local:4000/v1` (API docs at http://llm.local). Clients ask for an **alias**, and the ConfigMap maps each alias to a real model:

| Alias | Model | Used by |
|---|---|---|
| `chat-default` | `ollama_chat/llama3.2:3b` | Open WebUI (default model), later the agent and n8n |
| `embed-default` | `ollama/nomic-embed-text` | Open WebUI RAG embeddings |
| `chat-tools` | `ollama_chat/qwen2.5:3b` (`num_ctx: 8192`) | The file agent (tool calling) |

Every new service should use the OpenAI client with `base_url=http://litellm.llm.svc.cluster.local:4000/v1`, any API key and an alias, never an Ollama URL or model name. Then changing a model is one line in one file.

**Switch a model** (e.g. make `chat-default` use Qwen):

```bash
bash infra/scripts/host/02-pull-models.sh qwen2.5:3b     # on the WSL host
# edit infra/k3s/llm/litellm.yaml: chat-default -> model: ollama_chat/qwen2.5:3b
make llm-reload                                           # apply + restart LiteLLM
```

**Add a model:** pull it the same way and add a `model_list` entry with a new alias. The file has commented examples (`chat-tools`). It shows up in Open WebUI's model picker after `make llm-reload`.

Changing `embed-default` to another model changes the vectors. Re-index in Open WebUI afterwards (Admin Panel → Settings → Documents → Reindex).

**Test from the command line** (Windows or WSL, needs the `llm.local` hosts entry):

```bash
curl -s http://llm.local/v1/models
curl -s http://llm.local/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"chat-default","messages":[{"role":"user","content":"Say hi"}]}'
```

**Open WebUI settings come from its manifest.** [`ui/open-webui.yaml`](infra/k3s/ui/open-webui.yaml) sets `ENABLE_PERSISTENT_CONFIG=false`, so Open WebUI applies its env vars (LiteLLM connection, embeddings, sign-up off) on every start and ignores the settings saved in its database. Changes made in the Admin Panel last only until the pod restarts; to keep one, add the matching env var to the manifest. Accounts, chats and documents are still stored on its volume. Its session-signing key is the `open-webui-secret` Secret, which [`deploy.sh`](infra/scripts/deploy.sh) creates once, so restarts don't log anyone out.

**Other backends** are also just entries in the same file. The file has commented examples for each:
- **GPU Ollama on Windows** (`chat-gpu`). An integrated GPU such as Intel Arc can't be used from Ollama inside WSL, but Ollama running natively on Windows can try. Use its experimental Vulkan backend (`OLLAMA_VULKAN=1`) or Intel's IPEX-LLM build of Ollama. Set `OLLAMA_HOST=0.0.0.0` on Windows and allow port 11434 from WSL in Windows Firewall. Point `api_base` at the Windows host's IP as seen from WSL, which changes when WSL restarts. The GPU shares system RAM, so it doesn't add memory. Compare `chat-default` and `chat-gpu` speeds in Open WebUI before relying on it.
- **Hosted models** (`chat-cloud`). Put the API key in a `litellm-keys` Secret, not in Git. This is off by default: enabling it sends prompts off the machine (see [Non-Functional Requirements](#11-non-functional-requirements)).
- **vLLM** isn't used. It needs a supported GPU, which this laptop doesn't have; on CPU it's slower than Ollama and serves one model per process. If a GPU box becomes available, its OpenAI endpoint is one more entry (`model: hosted_vllm/<model>`, `api_base: http://<host>:8000/v1`).

When Langfuse arrives (Week 6), add `success_callback: ["langfuse"]` under `litellm_settings` and every LLM call is traced from this one place.

### 6.10 File agent (LangGraph + filesystem MCP)

Open **http://agent.local**, ask about your files, and expand each 🔧 line to see which tool the agent called and what it got back.

```text
agent.local ─► agent-ui (Streamlit, ui) ─► agent (LangGraph + FastAPI, agent) ─► LiteLLM chat-tools ─► qwen2.5:3b
                                                  │
                                                  └─ MCP streamable HTTP ─► mcp-filesystem ─► E:\ai-files (read-only)
```

| Piece | Code | Manifest |
|---|---|---|
| Filesystem MCP server: `list_dir`, `search_files`, `read_file` | [`mcp-servers/filesystem/`](mcp-servers/filesystem/server.py) | [`agent/agent.yaml`](infra/k3s/agent/agent.yaml) |
| Agent: LangGraph loop model → tools → model; `POST /chat`, `GET /tools` | [`agent/`](agent/graph.py) | [`agent/agent.yaml`](infra/k3s/agent/agent.yaml) |
| UI | [`ui/app.py`](ui/app.py) | [`ui/agent-ui.yaml`](infra/k3s/ui/agent-ui.yaml) |

**The shared folder** is `E:\ai-files` (`/mnt/e/ai-files` in WSL). Put text files there (Markdown, notes, code, CSV); the agent sees changes immediately. It's mounted read-only and every path is checked against the folder, so the agent can't write anything or reach other files. To share another folder, change the `hostPath` in [`agent/agent.yaml`](infra/k3s/agent/agent.yaml) and re-apply.

**Changing the code:** edit, `make test`, then `make images` (or `bash infra/scripts/build-images.sh agent` for one image). The script builds with Docker, imports the image into k3s and restarts the deployment. Images are tagged `local-ai/<name>:dev` with `imagePullPolicy: Never`; GHCR comes with CI in Week 7.

**Adding a tool:** run another MCP server (streamable HTTP) and add it to `MCP_SERVERS` in [`agent/agent.yaml`](infra/k3s/agent/agent.yaml). The agent loads every server's tools on start; no agent code changes.

**What to expect from a 3B model on CPU** (reference machine): 2 s for a question that needs no tool, 10–25 s for one or two tool calls. The tools are built to forgive small-model mistakes: `list_dir` shows two levels at once, and `read_file("readme")` finds `README.md`. The system prompt ([`agent/prompts/system.md`](agent/prompts/system.md)) spells out find → read → answer. Answers can still pad facts with loose summary; check the 🔧 results. Conversations live in the agent's memory and are lost when its pod restarts.

### 6.11 Cluster dashboard (Headlamp)

Open **http://headlamp.local** to browse pods, logs, events and resource usage, open a shell in a container, or edit a resource. It's deployed by `make deploy` from [`ui/headlamp.yaml`](infra/k3s/ui/headlamp.yaml) (image pinned by tag + digest, like LiteLLM).

**Logging in:** Headlamp asks for a token, not a password. Copy it with:

| From Windows (PowerShell, repo folder) | Inside Ubuntu (repo folder) |
|---|---|
| `.\infra\scripts\platform.ps1 headlamp-token` (copies it to the clipboard; runs as root, so no Ubuntu password is needed) | `make headlamp-token` (prints it) |

The token belongs to the `ui/headlamp` ServiceAccount, which is **cluster-admin**: anyone who has it can change or delete anything in the cluster. That's acceptable while `headlamp.local` is reachable only from this PC (WSL NAT). Before exposing it, bind the ServiceAccount to the read-only `view` ClusterRole instead. To rotate the token: `kubectl -n ui delete secret headlamp-token`, then re-apply the manifest.

New hostname: re-run [`windows-hosts.ps1`](infra/scripts/host/windows-hosts.ps1) (admin) to add `headlamp.local`.

---

## 7. CI/CD and GitOps

```text
Push to GitHub
   ↓
GitHub Actions: test + build image
   ↓
Push to GHCR
   ↓
ArgoCD (in k3s) pulls manifests
   ↓
Deploys to laptop k3s
```

| Component | Cost / limit |
|---|---|
| GitHub Actions | Free tier, 2,000 min/month (private repos; unlimited for public) |
| GHCR | 500 MB free for private packages |
| ArgoCD | Runs locally, no cost |
| Self-hosted runner | Optional, unlimited free minutes |

**Why ArgoCD:** it runs *inside* the cluster and pulls from GitHub, so the laptop never needs inbound network access.

---

## 8. Resource Budget

| Service | RAM (request) |
|---|---|
| k3s core | 500 MB |
| Ollama (3B model, on the WSL host) | 4 GB |
| LiteLLM gateway | 256 MB (limit 1 GB) |
| Qdrant | 512 MB |
| Postgres | 512 MB |
| MinIO | 512 MB |
| MLflow | 512 MB |
| Dagster | 1 GB |
| BentoML | 512 MB |
| LangGraph + MCP servers | 1.5 GB |
| Open WebUI + Agent UI | 768 MB |
| Headlamp | 64 MB (limit 256 MB) |
| n8n | 512 MB |
| Langfuse | 512 MB |
| Prometheus + Grafana | 768 MB |
| ArgoCD | 1.3 GB |
| **Total (core, steady state)** | **~13.7 GB** |
| **Peak (during training)** | **up to WSL cap of 18 GB** |
| **Headroom inside WSL at steady state** | **~4.3 GB** |

Fits in the 18 GB WSL allocation, leaving ~14 GB for Windows. Every workload must set Kubernetes `requests` and `limits`. Ollama sits outside k3s, so its 4 GB counts against the WSL cap but not against pod limits.

> **Why 18 GB, not 24 GB:** on the dev machine Windows uses ~8–15 GB with normal apps open, so a 24 GB WSL cap would overcommit the 32 GB machine and cause paging. At 18 GB the headroom is thin (~4.3 GB), so trim the stack where possible (e.g. ArgoCD core mode, Langfuse v2) and close heavy Windows apps before training runs.

---

## 9. Workflows (Functional Requirements)

| # | Workflow | Target latency | Main components |
|---|---|---|---|
| 1 | Chat + memory | 2–3 s | Ollama, memory MCP, Open WebUI |
| 2 | File search | 2–4 s | filesystem MCP |
| 3 | RAG Q&A | 3–5 s | LlamaIndex, Qdrant, nomic-embed-text |
| 4 | Email triage | 30–60 s | n8n, LLM classification |
| 5 | Calendar | 2–4 s | time MCP, n8n |
| 6 | Web research | 15–30 s | web-search + fetch MCP |
| 7 | Multi-step agent | 15–30 s | LangGraph planning + multiple tools |
| 8 | Voice assistant | 3–6 s | Speech-to-text + TTS + agent |
| 9 | OCR pipeline | 4–8 s | OCR engine + MinIO + RAG index |
| 10 | Daily briefing | 30–60 s | n8n schedule + web + calendar + LLM summary |

Latencies are targets for CPU-only 3B models and should be measured and reported via Langfuse.

---

## 10. UI Access

| UI | URL |
|---|---|
| Chat (Open WebUI) | http://chat.local |
| LLM gateway (LiteLLM API docs) | http://llm.local |
| Agent UI (Streamlit, file agent) | http://agent.local |
| Cluster dashboard (Headlamp) | http://headlamp.local |
| MLflow | http://mlflow.local |
| Dagster | http://dagster.local |
| n8n | http://n8n.local |
| Langfuse | http://langfuse.local |
| Grafana | http://grafana.local |
| MinIO | http://minio.local |
| Qdrant | http://qdrant.local/dashboard |
| ArgoCD | http://argocd.local |

---

## 11. Non-Functional Requirements

- **Privacy:** all inference and data stay on the laptop; no external LLM APIs. LiteLLM can route to hosted models, but none is configured by default.
- **Cost:** $0 — only open-source software and GitHub free tier.
- **Hardware:** runs CPU-only on 32 GB RAM; no GPU dependency.
- **Reproducibility:** full platform deployable from the repo (`kubectl apply` or ArgoCD sync).
- **Observability:** every LLM call traced in Langfuse; every service scraped by Prometheus.
- **Resource safety:** all pods have requests/limits (namespace defaults in `limits.yaml`); Ollama capped at 4 cores and one request at a time.
- **Extensibility:** new tools added as MCP servers without changing agent core.
- **Security:** secrets kept out of Git (Kubernetes Secrets / sealed secrets); no inbound ports exposed.

---

## 12. Thermal Management

| Action | Expected impact | How |
|---|---|---|
| Undervolt CPU (-100 mV) | 10–20 °C cooler | Only if your BIOS allows it (ThrottleStop / Intel XTU). Many laptops since 2020 lock it (Plundervolt fix); the reference Dell does |
| Limit max CPU state to 80% | 5–10 °C cooler | [`windows-thermal.ps1`](infra/scripts/host/windows-thermal.ps1); anything under 100% also turns Turbo Boost off. Undo with `-Max 100` |
| Ollama: hard CPU cap | 5–10 °C cooler | [`03-ollama-config.sh`](infra/scripts/host/03-ollama-config.sh): `CPUQuota=400%`, `OLLAMA_NUM_PARALLEL=1`. There is no `OLLAMA_NUM_THREADS` setting; Ollama already uses one thread per physical core |
| k3s resource limits | Prevents load spikes | Per-pod limits, plus namespace defaults in [`limits.yaml`](infra/k3s/limits.yaml) (max 2 CPU per container) |
| Start the platform only when needed | No idle heat | `platform.ps1 up` / `down` ([6.6](#66-start-and-stop-the-platform)) |
| Cooling stand (e.g. TopMate C302) | 10–18 °C cooler | Physical |
| Elevate back of laptop | 5–8 °C cooler | Physical |
| Schedule training at night | Heat when ambient is cool | Dagster schedules (Week 4) |
| Monitor with HWiNFO / Core Temp | Know actual temps | Windows-side tool; `sensors` does not work inside WSL, and Windows needs admin rights to read temperatures |

On the reference machine (i7-9850H) the 80% cap slowed a short Ollama reply from ~10.9 s to ~13.8 s, including model load.

---

## 13. 8-Week Build Plan

| Week | Focus | Deliverable |
|---|---|---|
| 1 | k3s + Ollama + Qdrant | Chat works ✅ |
| 2 | LangGraph + filesystem MCP | File agent ✅ |
| 3 | RAG (LlamaIndex + Qdrant) | Doc Q&A |
| 4 | MLflow + Dagster + training | Model trained |
| 5 | BentoML + agent integration | Model exposed as agent tool |
| 6 | n8n + Langfuse + Grafana | Automation + traces |
| 7 | ArgoCD + GitHub Actions | GitOps CI/CD |
| 8 | Voice + OCR + docs + demo | Full platform |

### Definition of done per week
- Manifests committed under `infra/k3s/`
- Service reachable at its `*.local` URL
- Tests in `tests/` pass in CI
- Short notes added under `docs/`

---

## 14. Key Decisions

- ✅ Monorepo (not split repos)
- ✅ k3s in WSL2 (not Docker Desktop)
- ✅ 3B models (no GPU needed)
- ✅ ArgoCD GitOps (no inbound access)
- ✅ GitHub Actions + GHCR (free tier)
- ✅ MCP-based tools (standard, extensible)
- ✅ ~13.7 GB core RAM (fits the 18 GB WSL allocation)
- ✅ Ollama on the WSL host, not in k3s (simpler, one copy of the models)
- ✅ LiteLLM gateway in front of all models: apps use aliases, so switching or adding a model is a config change
- ✅ No vLLM (needs a supported GPU; on CPU it's slower than Ollama)
- ✅ 8-week build plan
- ✅ Fully self-hosted, private, free

---

## 15. Open Issues and Risks

| Item | Notes |
|---|---|
| Ollama placement | **Decided:** WSL host (systemd), reached by pods at `http://ollama.llm.svc.cluster.local:11434`. Trade-off: ArgoCD doesn't manage Ollama; its settings live in [`03-ollama-config.sh`](infra/scripts/host/03-ollama-config.sh). The `10.42.0.1` address in `llm/ollama-host.yaml` assumes k3s's default pod network on a single node. |
| Langfuse footprint | Langfuse v3 needs Postgres + ClickHouse + Redis + MinIO; 512 MB is optimistic. Budget ~1.5–2 GB or use Langfuse v2 (Postgres only). |
| ArgoCD memory | 1.3 GB is significant; consider disabling Dex/notifications or using ArgoCD core mode. |
| GHCR 500 MB limit | Applies to private packages; keep images small (slim bases, multi-stage builds) and run `cleanup.yml`. Public images are free. |
| Voice/OCR tooling | Not yet specified — candidates: faster-whisper (STT), Piper (TTS), Tesseract / PaddleOCR (OCR). |
| Email/Calendar access | Requires OAuth credentials for the chosen provider; store as Kubernetes Secrets. |
| 3B model quality | `qwen2.5:3b` (`chat-tools`) calls tools reliably once the prompt gives explicit steps and the tools tolerate wrong paths; `llama3.2:3b` is weaker. Still seen: answers padded with loose summary, and the odd unneeded tool call. Re-test after changing the model or prompt (the `make status` agent check, or the questions in 6.10). |
| Agent latency | File search (workflow 2) measures 10–25 s, not the 2–4 s target: each tool call is a full model round trip on CPU. |
| WSL networking | **Resolved:** Traefik listens on the WSL host's ports and hosts entries point at `::1` ([6.7](#67-local-dns-for-local-hostnames)), so a changing WSL IP doesn't matter. Needs WSL's default NAT mode with `localhostForwarding=true`. |
| Disk space | Keep the distro (and so models, images, volumes) on a drive with ~100 GB free; the assessment checks this. On the reference machine it lives on a second SSD. |
| Windows memory pressure | Mitigated with `memory=18GB`, but steady-state headroom inside WSL is only ~4.3 GB. Watch it as services are added. |
| LiteLLM image | **Pinned** to `v1.103.1` (tag + digest) in [`llm/litellm.yaml`](infra/k3s/llm/litellm.yaml). Upgrade deliberately: change the tag, apply, run `make status`. No master key: fine while the API is reachable only from this PC, but add one (a Secret) before exposing it. |
| Open WebUI config | **Resolved:** settings come from env vars on every start (`ENABLE_PERSISTENT_CONFIG=false`), so Admin Panel changes don't survive a restart ([6.9](#69-llm-gateway-litellm-switching-and-adding-models)). |
| Pod restart counts | **Resolved:** `up` replaces the previous run's pods ([6.6](#66-start-and-stop-the-platform)), so `RESTARTS` counts only crashes in the current run. |

---

## 16. Deliverables

- Local AI agent platform running on k3s
- 10 working end-to-end workflows
- MCP-based tool system
- RAG + classical ML
- Full MLOps (MLflow, Dagster, BentoML, Optuna, Evidently)
- LLMOps / AIOps (Langfuse, Prometheus, Grafana, n8n)
- k3s + ArgoCD GitOps
- GitHub Actions CI/CD to GHCR
- Portfolio-ready repo with docs and demo
- Hands-on skills: agents, MCP, Kubernetes, LLMOps

---

## License

[MIT](LICENSE) © 2026 Nixon Varghese

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
10. [Endpoints](#10-endpoints)
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
| Ingress | Traefik (bundled with k3s) | Host-based routing to `*.ai.local` UIs |
| LLM | Ollama: `llama3.2:3b`, `qwen2.5:3b`, `phi3:mini` | CPU inference |
| Embeddings | `nomic-embed-text` (via Ollama) | Vector embeddings for RAG |
| LLM gateway | LiteLLM | One OpenAI-compatible API and model aliases for every backend |
| Agent | LangGraph | Stateful agent graph / orchestration |
| Protocol | MCP | Standard tool interface between agent and tools |
| Vector DB | Qdrant | Embedding storage and similarity search |
| Database | Postgres / SQLite | App state, metadata, backends for MLflow/n8n/Langfuse |
| Object Storage | SeaweedFS | S3-compatible artifact and document storage (MinIO went source-only in late 2025, [6.13](#613-training-pipeline-mlflow--dagster--optuna)) |
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
Windows 11 (32 GB) ── browser ──► http://*.ai.local (hosts file → ::1 → WSL)
   └── WSL2 (18 GB RAM, 8 cores)
         └── Ubuntu 26.04 (systemd enabled; services start on demand, see 6.6)
               ├── Ollama (systemd service on the WSL host, :11434)
               ├── Docker Engine (image builds / compose only, own image store)
               └── k3s
                     ├── kube-system:   Traefik on host ports 80/443, CoreDNS, local-path storage
                     ├── llm:           LiteLLM gateway (:4000) + Service "ollama" → Ollama on the host
                     ├── storage:       Qdrant, SeaweedFS (S3), Postgres
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
│   │   ├── storage/seaweedfs.yaml # S3 object storage (buckets mlflow, dagster)
│   │   ├── storage/postgres.yaml  # metadata DBs for MLflow and Dagster
│   │   ├── mlops/mlflow.yaml      # tracking server + model registry (6.13)
│   │   ├── mlops/dagster.yaml     # webserver + daemon (schedules, runs)
│   │   ├── mlops/bentoml.yaml
│   │   ├── agent/agent.yaml      # file agent API + filesystem MCP server
│   │   ├── agent/rag.yaml        # RAG: mcp-rag search server + rag-index CronJob (6.12)
│   │   ├── ui/open-webui.yaml
│   │   ├── ui/agent-ui.yaml      # Streamlit agent UI (agent.ai.local)
│   │   ├── ui/headlamp.yaml      # Kubernetes dashboard (headlamp.ai.local)
│   │   ├── automation/n8n.yaml
│   │   ├── observability/langfuse.yaml
│   │   ├── auth/authelia.yaml    # single sign-on for every *.ai.local UI (6.14)
│   │   ├── ingress/ingresses.yaml # *.ai.local, HTTPS, behind auth/authelia
│   │   ├── ingress/tls.yaml       # Traefik's default certificate (*.ai.local)
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
│       │   ├── 06-local-tls.sh      # local CA + *.ai.local certificate (6.14)
│       │   ├── windows-hosts.ps1    # *.ai.local → ::1 in the hosts file (admin)
│       │   ├── windows-trust-ca.ps1 # Windows trusts the local CA
│       │   └── windows-thermal.ps1
│       ├── platform.ps1    # up / down / status from Windows
│       ├── platform.sh     # up / down / status inside Ubuntu
│       ├── deploy.sh
│       ├── build-images.sh # build our images, load them into k3s (make images)
│       ├── teardown.sh     # delete all workloads and their volumes
│       ├── screenshots.ps1 # capture the UIs into docs/screenshots/ (README 10.4)
│       ├── rag-index.sh    # run the RAG indexer now (make rag-index)
│       ├── set-login.sh    # choose the single sign-on username + password
│       └── status.sh
├── agent/                  # LangGraph agent (6.10)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py             # FastAPI: POST /chat, GET /tools
│   ├── graph.py            # retrieve -> answer, else model -> tools loop (6.12)
│   └── prompts/system.md
├── mcp-servers/
│   ├── filesystem/         # read-only list/search/read over one folder (6.10)
│   ├── rag/                # LlamaIndex indexer + search_documents over Qdrant (6.12)
│   ├── web-search/
│   ├── fetch/
│   ├── memory/
│   ├── sqlite/
│   └── time/
├── mlops/mlflow/           # MLflow server image (adds the Postgres driver and boto3)
├── pipelines/              # Dagster image + code (6.13)
│   ├── dagster.yaml        # instance: Postgres storage, run queue, logs in S3
│   ├── workspace.yaml
│   └── triage/             # data.py (download, split), train.py (Optuna + MLflow), definitions.py
├── serving/
│   └── service.py
├── n8n/workflows/
├── ui/                     # Streamlit agent UI
├── data/
├── tests/                  # pytest, no cluster or LLM needed (make test)
├── docs/
│   └── screenshots/        # UI screenshots (README 10.4)
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

### 6.7 Local DNS for `*.ai.local` hostnames

Script: [`windows-hosts.ps1`](infra/scripts/host/windows-hosts.ps1) (admin PowerShell, from the repo folder). It backs up the hosts file, adds the lines below between `# BEGIN/END local-ai-platform` markers, and is safe to re-run; `-Remove` takes them out again. Manual equivalent, in `C:\Windows\System32\drivers\etc\hosts` (as admin):

```text
::1 auth.ai.local
::1 chat.ai.local
::1 llm.ai.local
::1 agent.ai.local
::1 mlflow.ai.local
::1 dagster.ai.local
::1 n8n.ai.local
::1 langfuse.ai.local
::1 grafana.ai.local
::1 s3.ai.local
::1 qdrant.ai.local
::1 argocd.ai.local
::1 headlamp.ai.local
```

One name per line: Windows treats extra names on a line as aliases of the first, and those don't resolve for `::1`.

Use `::1`, not `127.0.0.1`. Traefik runs on the WSL host's ports 80/443 ([traefik-config.yaml](infra/k3s/ingress/traefik-config.yaml)), and WSL forwards those to Windows' IPv6 localhost only. `http://localhost/` works for the same reason.

### 6.8 Thermal settings (optional)

See [Thermal Management](#12-thermal-management). [`windows-thermal.ps1`](infra/scripts/host/windows-thermal.ps1) caps the CPU at 80%; the Ollama cap is part of 6.3.


### 6.9 LLM gateway (LiteLLM): switching and adding models

[`llm/litellm.yaml`](infra/k3s/llm/litellm.yaml) runs [LiteLLM](https://docs.litellm.ai/) as an OpenAI-compatible gateway at `http://litellm.llm.svc.cluster.local:4000/v1` (API docs at https://llm.ai.local). Clients ask for an **alias**, and the ConfigMap maps each alias to a real model:

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

**Test from the command line** (Windows or WSL, needs the `llm.ai.local` hosts entry):

```bash
curl -s https://llm.ai.local/v1/models
curl -s https://llm.ai.local/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"chat-default","messages":[{"role":"user","content":"Say hi"}]}'
```

**Open WebUI settings come from its manifest.** [`ui/open-webui.yaml`](infra/k3s/ui/open-webui.yaml) sets `ENABLE_PERSISTENT_CONFIG=false`, so Open WebUI applies its env vars (LiteLLM connection, embeddings, sign-up off) on every start and ignores the settings saved in its database. Changes made in the Admin Panel last only until the pod restarts; to keep one, add the matching env var to the manifest. Accounts, chats and documents are still stored on its volume. Its session-signing key is the `open-webui-secret` Secret, which [`deploy.sh`](infra/scripts/deploy.sh) creates once, so restarts don't log anyone out.

**Other backends** are also just entries in the same file. The file has commented examples for each:
- **GPU Ollama on Windows** (`chat-gpu`). An integrated GPU such as Intel Arc can't be used from Ollama inside WSL, but Ollama running natively on Windows can try. Use its experimental Vulkan backend (`OLLAMA_VULKAN=1`) or Intel's IPEX-LLM build of Ollama. Set `OLLAMA_HOST=0.0.0.0` on Windows and allow port 11434 from WSL in Windows Firewall. Point `api_base` at the Windows host's IP as seen from WSL, which changes when WSL restarts. The GPU shares system RAM, so it doesn't add memory. Compare `chat-default` and `chat-gpu` speeds in Open WebUI before relying on it.
- **Hosted models** (`chat-cloud`). Put the API key in a `litellm-keys` Secret, not in Git. This is off by default: enabling it sends prompts off the machine (see [Non-Functional Requirements](#11-non-functional-requirements)).
- **vLLM** isn't used. It needs a supported GPU, which this laptop doesn't have; on CPU it's slower than Ollama and serves one model per process. If a GPU box becomes available, its OpenAI endpoint is one more entry (`model: hosted_vllm/<model>`, `api_base: http://<host>:8000/v1`).

When Langfuse arrives (Week 6), add `success_callback: ["langfuse"]` under `litellm_settings` and every LLM call is traced from this one place.

### 6.10 File agent (LangGraph + filesystem MCP)

Open **https://agent.ai.local**, ask about your files, and expand each 🔧 line to see which tool the agent called and what it got back.

```text
agent.ai.local ─► agent-ui (Streamlit, ui) ─► agent (LangGraph + FastAPI, agent) ─► LiteLLM chat-tools ─► qwen2.5:3b
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

Open **https://headlamp.ai.local** to browse pods, logs, events and resource usage, open a shell in a container, or edit a resource. It's deployed by `make deploy` from [`ui/headlamp.yaml`](infra/k3s/ui/headlamp.yaml) (image pinned by tag + digest, like LiteLLM).

**Logging in:** Headlamp asks for a token, not a password. Copy it with:

| From Windows (PowerShell, repo folder) | Inside Ubuntu (repo folder) |
|---|---|
| `.\infra\scripts\platform.ps1 headlamp-token` (copies it to the clipboard; runs as root, so no Ubuntu password is needed) | `make headlamp-token` (prints it) |

The token belongs to the `ui/headlamp` ServiceAccount, which is **cluster-admin**: anyone who has it can change or delete anything in the cluster. That's acceptable while `headlamp.ai.local` is reachable only from this PC (WSL NAT). Before exposing it, bind the ServiceAccount to the read-only `view` ClusterRole instead. To rotate the token: `kubectl -n ui delete secret headlamp-token`, then re-apply the manifest.

New hostname: re-run [`windows-hosts.ps1`](infra/scripts/host/windows-hosts.ps1) (admin) to add `headlamp.ai.local`.

### 6.12 Document Q&A (RAG: LlamaIndex + Qdrant)

Ask https://agent.ai.local about what your documents *say* ("What was decided in the last meeting?"). The answer comes from the passages that match, with a **Sources:** line of `file:lines`; expand the 🔧 `search_documents (auto)` line to see them.

```text
E:\ai-files ─► rag-index (CronJob, every 15 min) ─ LlamaIndex: split ─► embed-default (LiteLLM) ─► Qdrant "docs"
                                                                           only new/changed files (sha256)

question ─► agent: retrieve ─► mcp-rag search_documents ─► passages above the score cut-off?
                    ├─ yes ─► answer from them (no tools, 1 model call) ─► answer + Sources
                    │           └─ model says NO_ANSWER ─┐
                    └─ no (or "which files...") ─────────┴─► tool loop (list_dir / read_file / search_files)
```

| Piece | Code | Manifest |
|---|---|---|
| Indexer: text files → 256-token chunks with their line range → `embed-default` → Qdrant | [`rag_index.py`](mcp-servers/rag/rag_index.py) | CronJob `rag-index` in [`agent/rag.yaml`](infra/k3s/agent/rag.yaml) |
| Search server: MCP tool `search_documents` | [`rag_server.py`](mcp-servers/rag/rag_server.py) | Deployment `mcp-rag` in [`agent/rag.yaml`](infra/k3s/agent/rag.yaml) |
| Embeddings through LiteLLM, with nomic's `search_query:` / `search_document:` prefixes | [`rag_store.py`](mcp-servers/rag/rag_store.py) | ConfigMap `rag-config` |
| Agent: retrieve first, answer from passages, fall back to the tool loop | [`agent/graph.py`](agent/graph.py) | `MCP_SERVERS` in [`agent/agent.yaml`](infra/k3s/agent/agent.yaml) |

**Indexing** runs every 15 minutes while the platform is up, and only re-embeds files whose content changed, so a run with nothing new takes seconds. Put a file in `E:\ai-files` and run `make rag-index` (inside Ubuntu) to index it now. After changing the embedding model, its prefixes or the chunk size, run `make rag-index ARGS=--rebuild`. Indexed: text files up to 1 MB (`.md`, `.txt`, `.csv`, `.json`, `.yaml`, code, ...); PDFs and Office files come with OCR in Week 8.

**Why the agent retrieves before asking the model:** with `qwen2.5:3b` on CPU (measured 2026-10-03), handing the model a search tool went wrong in three ways. It often answered "I don't have access" instead of searching. When it did search, it searched again or called other tools after getting the passages, which cost 12–42 s. And with tools bound it sometimes returned an empty reply. Retrieving first and answering without tools takes **3–11 s (median ~7 s)** and was right on every test question. Passages count only if they score at least `MIN_SCORE` 0.60 and are within `SCORE_MARGIN` 0.05 of the best one: right passages scored 0.66–0.77, off-topic questions at most 0.53. Questions asking *which files* exist skip retrieval; otherwise the model described the README instead of listing the folder.

**Tuning** (in `rag-config`, then `kubectl -n agent rollout restart deploy/mcp-rag`): `TOP_K` passages (4), `MIN_SCORE`, `SCORE_MARGIN`; `CHUNK_TOKENS` / `CHUNK_OVERLAP` need a `--rebuild`. The collection is visible at https://qdrant.ai.local/dashboard → Collections → `docs`.

### 6.13 Training pipeline (MLflow + Dagster + Optuna)

A classical-ML pipeline next to the LLM side: a **message-triage** classifier (spam vs. normal message) trained on the public [SMS Spam Collection](https://archive.ics.uci.edu/dataset/228/sms+spam+collection) (5,574 messages, 13% spam). In Week 5 it becomes an agent tool (`classify_message`) and the basis of workflow 4 (email triage).

```text
Dagster (dagster.ai.local)  daemon: nightly 02:00 Asia/Dubai, or `make train` / "Materialize all"
  sms_spam_raw ─► sms_spam_split ─► triage_model ──────────────► check: test F1 >= 0.90
  (UCI, sha256)   (80/20, seed 42)   Optuna: 30 trials × 5-fold CV
       │                │            final fit + test metrics
       └── SeaweedFS s3://dagster ───┘        │
                                              ▼
                              MLflow (mlflow.ai.local): runs + 30 child runs, model "message-triage"
                              Postgres (runs, registry)   SeaweedFS s3://mlflow (model files)
                              alias "champion" moves only when test F1 improves
```

| Piece | Code | Manifest |
|---|---|---|
| Postgres 18: databases `mlflow`, `dagster` | — | [`storage/postgres.yaml`](infra/k3s/storage/postgres.yaml) |
| SeaweedFS (`weed mini`): S3 API + admin UI at https://s3.ai.local | — | [`storage/seaweedfs.yaml`](infra/k3s/storage/seaweedfs.yaml) |
| MLflow server: tracking, registry, artifact proxy to `s3://mlflow` | [`mlops/mlflow/`](mlops/mlflow/Dockerfile) | [`mlops/mlflow.yaml`](infra/k3s/mlops/mlflow.yaml) |
| Dagster webserver + daemon | [`pipelines/`](pipelines/dagster.yaml) | [`mlops/dagster.yaml`](infra/k3s/mlops/dagster.yaml) |
| Assets, job, nightly schedule, F1 check | [`triage/definitions.py`](pipelines/triage/definitions.py) | |
| Dataset download (pinned sha256) and split | [`triage/data.py`](pipelines/triage/data.py) | |
| Optuna tuning, MLflow logging, registry promotion | [`triage/train.py`](pipelines/triage/train.py) | |

**Running it:** the schedule runs `triage_training` at 02:00 local time, when the laptop is coolest (§12). If the platform is down then, that night is skipped (Dagster doesn't replay missed nights). To train now: `make train` inside Ubuntu, or https://dagster.ai.local → *Jobs* → `triage_training` → *Materialize all*. Runs queue and execute one at a time in the daemon pod (max 2 CPUs).

**First run (2026-10-05):** 13.5 min on CPU (30 trials, ~25 s each, ~1.9 cores, 1.3 GiB). Best model: character 2–5-grams, `C` 49, balanced class weights.

| Test set (1,115 messages) | F1 (spam) | Precision | Recall | Accuracy | ROC AUC |
|---|---|---|---|---|---|
| `message-triage` v1 (champion) | **0.976** | **1.000** | 0.953 | 99.4% | 0.998 |

Precision 1.0 means no normal message was flagged as spam; recall 0.953 means 1 in 21 spam messages got through.

**Using the model:** `models:/message-triage@champion` is always the best version so far. Any pod with `MLFLOW_TRACKING_URI=http://mlflow.mlops.svc.cluster.local:5000` can load it; files come through MLflow's artifact proxy, so no S3 keys are needed:

```python
import mlflow, pandas as pd
model = mlflow.pyfunc.load_model("models:/message-triage@champion")
model.predict(pd.DataFrame({"text": ["You have won a voucher, call now", "Dinner at 6?"]}))  # ['spam', 'ham']
```

**Credentials:** generated once by `deploy.sh` and kept only in the cluster (Secrets `storage/postgres-secret`, `storage/seaweedfs-secret`, copies in `mlops`). `make s3-credentials` prints the SeaweedFS admin login (user `admin`) and the S3 key pair.

**Why SeaweedFS, not MinIO:** MinIO switched to a source-only distribution in late 2025, so there are no maintained images. SeaweedFS is Apache-2.0, actively maintained, and the replacement Kubeflow Pipelines chose. Its `mini` mode runs master, volume, filer, S3 API and admin UI in one ~180 MB process. Anything that speaks S3 (boto3, MLflow, Dagster) uses it unchanged; moving to AWS S3 or Azure Blob later means changing the endpoint URL.

**Three things that bit during setup (fixed in the manifests):** MLflow 3 starts a GenAI job runner of ~8 Python processes (~240 MB each) by default and was OOM-killed at 1 GiB, so it's off (`MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`; 400 MB now). SQLAlchemy now picks psycopg 3 for `postgresql://`, so the MLflow image ships psycopg 3. Dagster's Postgres storage breaks under psycopg 3 (its `NOTIFY` query), so Dagster gets an explicit `postgresql+psycopg2://` URL.

### 6.14 Single sign-on and HTTPS (Authelia)

Every UI sits behind **one login**: open any `https://<name>.ai.local`, sign in once at https://auth.ai.local, and the session (12 h, or 2 h idle) opens all of them. Open WebUI, Headlamp and SeaweedFS keep their own login as a second layer.

```text
browser ─https─► Traefik (cert *.ai.local from the local CA)
                   ├─ auth.ai.local ─────────────────────────► Authelia: sign-in page
                   └─ any other *.ai.local ─ forwardAuth ─► Authelia: session cookie on ai.local?
                                                ├─ no  ─► 302 to auth.ai.local, back after sign-in
                                                └─ yes ─► the UI (chat, llm, agent, qdrant, headlamp, mlflow, dagster, s3)
```

| Piece | Where |
|---|---|
| Authelia 4.39 (users file, SQLite, brute-force lockout: 5 tries in 2 min → 10 min ban) | [`auth/authelia.yaml`](infra/k3s/auth/authelia.yaml) |
| Traefik middleware `auth/authelia` on every ingress; HTTP → HTTPS redirect | [`ingress/ingresses.yaml`](infra/k3s/ingress/ingresses.yaml), [`traefik-config.yaml`](infra/k3s/ingress/traefik-config.yaml) |
| Local CA + `*.ai.local` certificate (397 days; CA 10 years) | [`06-local-tls.sh`](infra/scripts/host/06-local-tls.sh) → Secret `kube-system/platform-tls`, [`ingress/tls.yaml`](infra/k3s/ingress/tls.yaml) |
| Windows trusts the CA (Chrome, Edge) | [`windows-trust-ca.ps1`](infra/scripts/host/windows-trust-ca.ps1) |
| Choose your username + password | [`set-login.sh`](infra/scripts/set-login.sh) |

**First setup** (after `make deploy`): 1) `.\infra\scripts\host\windows-hosts.ps1` (admin) for the `*.ai.local` names; 2) `.\infra\scripts\host\windows-trust-ca.ps1` and click *Yes* on Windows' certificate warning; 3) `.\infra\scripts\platform.ps1 set-login` to choose your username and password (typed in the terminal, stored only as an argon2 hash in Secret `auth/authelia-users`). Until step 3, the only user is a bootstrap `admin` with a random password (Secret `auth/authelia-initial`, deleted by set-login).

**Why the names changed from `*.local` to `*.ai.local`:** one sign-in has to cover every UI, so the session cookie is set on a parent domain, and browsers won't share a cookie across bare `.local`. Authelia also requires HTTPS, hence the local CA. Old `*.local` bookmarks no longer work.

**Changing the password:** run `set-login` again (it signs everyone out). **Forgot it:** same; there's no e-mail reset. **2FA:** set the rule in `authelia.yaml` to `two_factor`, apply, and register an authenticator app at https://auth.ai.local. **Renewing the certificate** (yearly): `wsl -u root -- bash infra/scripts/host/06-local-tls.sh --renew`.

**APIs:** in-cluster clients use the `*.svc.cluster.local` names and never pass the login. From Windows, `https://llm.ai.local` now needs a browser session; scripts should use a port-forward (§10.3).

**Gotchas fixed during setup:** Kubernetes injects `AUTHELIA_PORT=tcp://...` for a Service named `authelia`, which Authelia reads as config and refuses to start (`enableServiceLinks: false`). Authelia rewrites `/app/.healthcheck.env` on start, so its root filesystem can't be read-only. Traefik on the host network used WSL's DNS and couldn't resolve `authelia.auth.svc.cluster.local` (`dnsPolicy: ClusterFirstWithHostNet`).

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
| Postgres | 512 MB (measured 72 MB idle) |
| SeaweedFS (replaces MinIO) | 512 MB (measured 184 MB) |
| MLflow | 512 MB (measured 400 MB, job runner off) |
| Dagster | 1 GB (measured: webserver 590 MB, daemon 390 MB idle / 1.3 GB while training) |
| BentoML | 512 MB |
| LangGraph + MCP servers | 1.5 GB |
| Open WebUI + Agent UI | 768 MB |
| Headlamp | 64 MB (limit 256 MB) |
| Authelia (single sign-on) | 32 MB (limit 256 MB) |
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
| 3 | RAG Q&A | 3–5 s (measured 3–11 s, median ~7 s) | LlamaIndex, Qdrant, nomic-embed-text, mcp-rag |
| 4 | Email triage | 30–60 s | n8n, LLM classification |
| 5 | Calendar | 2–4 s | time MCP, n8n |
| 6 | Web research | 15–30 s | web-search + fetch MCP |
| 7 | Multi-step agent | 15–30 s | LangGraph planning + multiple tools |
| 8 | Voice assistant | 3–6 s | Speech-to-text + TTS + agent |
| 9 | OCR pipeline | 4–8 s | OCR engine + SeaweedFS + RAG index |
| 10 | Daily briefing | 30–60 s | n8n schedule + web + calendar + LLM summary |

Latencies are targets for CPU-only 3B models and should be measured and reported via Langfuse.

---

## 10. Endpoints

Every URL below opens from Windows once the platform is up (`.\local-up`) and the hosts entries exist ([6.7](#67-local-dns-for-local-hostnames)). In PowerShell use `curl.exe`, not `curl` (an alias for `Invoke-WebRequest`).

### 10.1 Open them one by one

Work down the list; each step depends only on the ones above it. If a step fails, run `.\infra\scripts\platform.ps1 status` and check that pod. Step 1 signs you in for all the others ([6.14](#614-single-sign-on-and-https-authelia)).

| # | Open | You should see | Quick check (PowerShell, signed out) |
|---|---|---|---|
| 0 | http://localhost:11434 | `Ollama is running` (host service, no login) | `curl.exe http://localhost:11434/api/tags` lists `llama3.2:3b`, `qwen2.5:3b`, `nomic-embed-text` |
| 1 | https://auth.ai.local | Authelia sign-in, then "Authenticated" with a *Logout* button; a padlock in the address bar | `curl.exe -s --ssl-no-revoke -o NUL -w "%{http_code}" https://auth.ai.local` → `200` |
| 2 | https://llm.ai.local | LiteLLM's API docs (Swagger) | `curl.exe -s --ssl-no-revoke -o NUL -w "%{http_code}" https://llm.ai.local` → `302` (to sign-in) |
| 3 | https://qdrant.ai.local/dashboard | Qdrant's web UI, collection `docs` from the RAG index (6.12) | same → `302` |
| 4 | https://chat.ai.local | Open WebUI's own sign-in (second layer); then pick `chat-default` and send "hi" | same → `302` |
| 5 | https://agent.ai.local | Agent UI. Ask "What was decided in the meeting on 2026-10-01?" (5–10 s) and expand the 🔧 line | same → `302` |
| 6 | https://headlamp.ai.local | Headlamp's token login: `.\infra\scripts\platform.ps1 headlamp-token`, paste. **Workloads → Pods** shows every pod ([6.11](#611-cluster-dashboard-headlamp)) | same → `302` |
| 7 | https://mlflow.ai.local | MLflow: *Models* → `message-triage` with alias `champion` ([6.13](#613-training-pipeline-mlflow--dagster--optuna)) | same → `302` |
| 8 | https://dagster.ai.local | Dagster: *Catalog* → `triage_model`, *Automation* → `triage_nightly` | same → `302` |
| 9 | https://s3.ai.local | SeaweedFS admin sign-in (second layer): user `admin`, password from `make s3-credentials` | same → `302` |

Any `*.ai.local` page answering `302` to `auth.ai.local` is up and protected; a `404` comes from Traefik (no Ingress for that name: a typo, or not deployed yet); a certificate warning means `windows-trust-ca.ps1` hasn't run (`curl.exe` needs `--ssl-no-revoke`: Windows' TLS asks for a revocation check that a private CA can't answer; browsers don't); "can't reach this site" means the hosts entry is missing.

### 10.2 Endpoint reference (live)

| Service | From Windows | In-cluster (pod to pod) | Useful paths |
|---|---|---|---|
| Ollama (on the WSL host) | http://localhost:11434 | `http://ollama.llm.svc.cluster.local:11434` | `/api/version`, `/api/tags` (installed models), `/api/generate`, `/api/chat`, `/api/embed` |
| LiteLLM gateway | https://llm.ai.local | `http://litellm.llm.svc.cluster.local:4000` | `/` API docs, `/v1/models`, `/v1/chat/completions`, `/v1/embeddings`, `/health/readiness` |
| Qdrant | https://qdrant.ai.local | `http://qdrant.storage.svc.cluster.local:6333` (REST), `:6334` (gRPC) | `/dashboard`, `/collections`, `/readyz` |
| Open WebUI | https://chat.ai.local | `http://open-webui.ui.svc.cluster.local:8080` | `/` |
| Agent UI (Streamlit) | https://agent.ai.local | `http://agent-ui.ui.svc.cluster.local:8501` | `/`, `/_stcore/health` |
| Headlamp | https://headlamp.ai.local | `http://headlamp.ui.svc.cluster.local:4466` | `/` |
| Agent API (LangGraph) | not exposed, see 10.3 | `http://agent.agent.svc.cluster.local:8000` | `POST /chat`, `GET /tools`, `GET /health`, `/docs` (FastAPI) |
| Filesystem MCP server | not exposed, see 10.3 | `http://mcp-filesystem.agent.svc.cluster.local:8000` | `/mcp` (MCP streamable HTTP), `/health` |
| RAG MCP server | not exposed, see 10.3 | `http://mcp-rag.agent.svc.cluster.local:8000` | `/mcp` (tool `search_documents`), `/health` |
| MLflow | https://mlflow.ai.local | `http://mlflow.mlops.svc.cluster.local:5000` | `/` UI, `/health`, `/api/2.0/mlflow/...` (REST), `/api/2.0/mlflow-artifacts/...` (artifact proxy) |
| Dagster | https://dagster.ai.local | `http://dagster-webserver.mlops.svc.cluster.local:3000` | `/` UI, `/server_info`, `/graphql` |
| SeaweedFS | https://s3.ai.local (admin UI) | `http://seaweedfs.storage.svc.cluster.local:8333` (S3 API), `:23646` (admin UI) | S3: buckets `mlflow`, `dagster`; keys from `make s3-credentials` |
| Postgres | not exposed, see 10.3 | `postgres.storage.svc.cluster.local:5432` | databases `mlflow`, `dagster` |

LiteLLM has no API key (README §15), so any client on this PC can call it. For example, from PowerShell:

```powershell
curl.exe https://llm.ai.local/v1/chat/completions -H "Content-Type: application/json" `
  -d '{\"model\":\"chat-default\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}]}'
```

### 10.3 Internal endpoints (port-forward)

The agent API and the MCP server have no Ingress on purpose: only the agent UI calls them. To try them from Windows, forward a port inside Ubuntu (leave it running, Ctrl+C to stop):

```bash
kubectl -n agent port-forward svc/agent 8000:8000            # then http://localhost:8000/docs
kubectl -n agent port-forward svc/mcp-filesystem 8001:8000   # then http://localhost:8001/health
kubectl -n agent port-forward svc/mcp-rag 8002:8000          # then http://localhost:8002/health
kubectl -n storage port-forward svc/seaweedfs 8333:8333      # S3 API at http://localhost:8333 (aws cli, boto3)
kubectl -n storage port-forward svc/postgres 5432:5432       # psql/DBeaver on localhost:5432
```

WSL forwards `localhost` ports to Windows, so the browser on Windows reaches them. The agent's `/docs` page lets you call `POST /chat` directly and see the raw `steps`.

### 10.4 Screenshots

Captured with [`screenshots.ps1`](infra/scripts/screenshots.ps1) (`.\infra\scripts\screenshots.ps1` with the platform up; re-run it after UI changes). It drives headless Chrome, asks the agent one document question, and leaves login pages at their sign-in screen.

| Agent UI (https://agent.ai.local): document question, retrieved passage and sources, 6.6 s on CPU | LiteLLM API docs (https://llm.ai.local) |
|---|---|
| ![Agent UI](docs/screenshots/agent.png) | ![LiteLLM](docs/screenshots/litellm.png) |
| **Qdrant dashboard: collection `docs`, 65 chunks, 768-dim cosine** | **Open WebUI sign-in (https://chat.ai.local)** |
| ![Qdrant](docs/screenshots/qdrant.png) | ![Open WebUI](docs/screenshots/chat.png) |
| **Headlamp token login (https://headlamp.ai.local)** | **MLflow registry: `message-triage` v1, alias `champion`, test F1 0.9759** |
| ![Headlamp](docs/screenshots/headlamp.png) | ![MLflow](docs/screenshots/mlflow.png) |
| **Dagster: `triage_model` materialized, check passed, nightly 02:00 GMT+4** | **SeaweedFS admin sign-in (https://s3.ai.local)** |
| ![Dagster](docs/screenshots/dagster.png) | ![SeaweedFS](docs/screenshots/s3.png) |

### 10.5 Planned (not deployed yet)

Their hosts entries already exist; until the service is deployed the URL returns Traefik's `404`.

| Service | URL | Week |
|---|---|---|
| n8n | https://n8n.ai.local | 6 |
| Langfuse | https://langfuse.ai.local | 6 |
| Grafana | https://grafana.ai.local | 6 |
| ArgoCD | https://argocd.ai.local | 7 |

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
| Schedule training at night | Heat when ambient is cool | Dagster schedule `triage_nightly`, 02:00 local; one run at a time, max 2 CPUs ([6.13](#613-training-pipeline-mlflow--dagster--optuna)) |
| Monitor with HWiNFO / Core Temp | Know actual temps | Windows-side tool; `sensors` does not work inside WSL, and Windows needs admin rights to read temperatures |

On the reference machine (i7-9850H) the 80% cap slowed a short Ollama reply from ~10.9 s to ~13.8 s, including model load.

---

## 13. 8-Week Build Plan

| Week | Focus | Deliverable |
|---|---|---|
| 1 | k3s + Ollama + Qdrant | Chat works ✅ |
| 2 | LangGraph + filesystem MCP | File agent ✅ |
| 3 | RAG (LlamaIndex + Qdrant) | Doc Q&A ✅ |
| 4 | MLflow + Dagster + training | Model trained ✅ |
| 5 | BentoML + agent integration | Model exposed as agent tool |
| 6 | n8n + Langfuse + Grafana | Automation + traces |
| 7 | ArgoCD + GitHub Actions | GitOps CI/CD |
| 8 | Voice + OCR + docs + demo | Full platform |

### Definition of done per week
- Manifests committed under `infra/k3s/`
- Service reachable at its `*.ai.local` URL
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
| Langfuse footprint | Langfuse v3 needs Postgres + ClickHouse + Redis + S3 (SeaweedFS can serve); 512 MB is optimistic. Budget ~1.5–2 GB or use Langfuse v2 (Postgres only). |
| ArgoCD memory | 1.3 GB is significant; consider disabling Dex/notifications or using ArgoCD core mode. |
| GHCR 500 MB limit | Applies to private packages; keep images small (slim bases, multi-stage builds) and run `cleanup.yml`. Public images are free. |
| Voice/OCR tooling | Not yet specified — candidates: faster-whisper (STT), Piper (TTS), Tesseract / PaddleOCR (OCR). |
| Email/Calendar access | Requires OAuth credentials for the chosen provider; store as Kubernetes Secrets. |
| 3B model quality | `qwen2.5:3b` (`chat-tools`) calls tools reliably once the prompt gives explicit steps and the tools tolerate wrong paths; `llama3.2:3b` is weaker. Still seen: answers padded with loose summary, and the odd unneeded tool call. Re-test after changing the model or prompt (the `make status` agent and RAG checks, or the questions in 6.10 and 6.12). |
| Agent latency | File search (workflow 2) measures 10–25 s, not the 2–4 s target: each tool call is a full model round trip on CPU. Document Q&A (workflow 3) avoids the round trip and measures 3–11 s against 3–5 s ([6.12](#612-document-qa-rag-llamaindex--qdrant)). |
| Image sizes | `local-ai/mlflow` 1.3 GB and `local-ai/pipelines` 1.1 GB (MLflow, Dagster, scikit-learn, pandas), on top of `mcp-rag`. Fine locally; for GHCR in Week 7 keep them public or slim them (e.g. `mlflow-skinny` for the server isn't enough: it lacks the server). |
| Nightly training | Runs only if the platform is up at 02:00; missed nights aren't replayed. Same data + fixed seed give the same score, so the champion only changes when the data or the search space does. |
| Single sign-on | **Resolved:** every UI is behind Authelia over HTTPS ([6.14](#614-single-sign-on-and-https-authelia)). One factor (password) for now; switch the rule to `two_factor` before exposing anything beyond this PC. The local CA's private key (`/var/lib/local-ai-ca`, root-only in WSL) can sign certificates your browser trusts: keep it there, and remove the CA with `windows-trust-ca.ps1 -Remove` if you retire the platform. |
| RAG image size | `local-ai/mcp-rag` is ~600 MB (LlamaIndex pulls NumPy, NLTK, SQLAlchemy, Pillow), against ~80 MB for the other images. Public GHCR images have no size limit; keep it public, or slim it before Week 7 if it must be private. |
| RAG routing | The agent skips retrieval for "which/what files..." and "list ... notes/files" questions (a regex in [`graph.py`](agent/graph.py)). Questions phrased otherwise go through retrieval, and the model can still answer them from passages instead of listing the folder. Unknown facts get a clumsy "I don't have access" rather than "I don't know". |
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

# Week 2: file agent (LangGraph + filesystem MCP)

**Deliverable:** an agent that answers questions about your files. ✅ (#6)

## What runs
- `mcp-filesystem`: read-only `list_dir`, `read_file`, `search_files` over `E:\ai-files`; every
  path is resolved and must stay inside the folder (no `..`, no symlinks out).
- `agent`: LangGraph loop model → tools → model, FastAPI `POST /chat`; tools are loaded from the
  MCP servers listed in `MCP_SERVERS`, so a new tool is a config change.
- `agent-ui`: Streamlit at https://agent.ai.local, shows every tool call (🔧).

## Decisions
- **`qwen2.5:3b` as `chat-tools`:** `llama3.2:3b` called tools unreliably.
- **Tools forgive small-model mistakes:** `list_dir` shows two levels at once, `read_file("readme")`
  finds `README.md`; the system prompt spells out find → read → answer.
- Images built locally and imported into k3s (`make images`), `imagePullPolicy: Never`, until
  CI pushes to GHCR (Week 7).

## Measured
- 2 s for a question without tools, 10–27 s with one or two tool calls (each call is a full
  model round trip on CPU). Workflow 2's 2–4 s target is not reachable on CPU.

"""HTTP API for the agent (FastAPI, port 8000).

    POST /chat   {"message": "...", "thread_id": "optional"}
                 -> {"thread_id", "answer", "steps": [{"tool", "args", "result"}], "seconds"}
    GET  /tools  tools loaded from the MCP servers
    GET  /health liveness

Conversations are kept per thread_id in SQLite (CHECKPOINT_DB, on a volume), so they survive
restarts; without it they live in memory. An MCP server that's down at start is retried on
later requests (every RELOAD_SECONDS), and its tools appear once it's up.
"""

import asyncio
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from graph import LLM_MODEL, MCP_SERVERS, MEMORY_TOOL, RETRIEVE_TOOL, build_graph, load_tools, text

log = logging.getLogger("agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def tracing():
    """Trace every agent run (LangGraph steps, model calls, tools) to Phoenix (README §6.16).

    Spans are batched in the background; while the observability profile is off the export just
    fails, so its errors are silenced instead of logged on every question."""
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
    if not endpoint:
        return
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from phoenix.otel import register

    # Not the global tracer: FastAPI emits spans for every request to a global one, and the
    # 10-second health probes would bury the agent runs. Only LangChain/LangGraph gets it.
    provider = register(project_name="agent", endpoint=f"{endpoint}/v1/traces", batch=True,
                        set_global_tracer_provider=False)
    LangChainInstrumentor().instrument(tracer_provider=provider)
    for name in ("opentelemetry.exporter.otlp.proto.http.trace_exporter", "opentelemetry.sdk._shared_internal"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


tracing()

# Model + tool round trips per question; stops a small model from looping forever
MAX_STEPS = int(os.environ.get("MAX_STEPS", "12"))

CHECKPOINT_DB = os.environ.get("CHECKPOINT_DB", "")
RELOAD_SECONDS = 60

_graph = None
_tools = []
_missing: list[str] = []
_loaded_at = 0.0
_checkpointer = None
_lock = asyncio.Lock()


async def checkpointer():
    global _checkpointer
    if _checkpointer is None and CHECKPOINT_DB:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        _checkpointer = AsyncSqliteSaver(await aiosqlite.connect(CHECKPOINT_DB))
    return _checkpointer


async def get_graph():
    """Build the graph on first use, so the agent starts even if an MCP server isn't up yet;
    rebuild it when a server that was down comes up (conversations are in the checkpointer)."""
    global _graph, _tools, _missing, _loaded_at
    async with _lock:
        if _graph is None or (_missing and time.time() - _loaded_at > RELOAD_SECONDS):
            _loaded_at = time.time()
            tools, missing = await load_tools()
            if _graph is None or len(tools) > len(_tools):
                _tools, _graph = tools, build_graph(tools, checkpointer=await checkpointer())
                log.info("loaded %d tools from %s: %s", len(tools), [s for s in MCP_SERVERS if s not in missing],
                         [t.name for t in tools])
            _missing = missing
            if missing:
                log.warning("MCP servers not reachable yet (retried in %ds): %s", RELOAD_SECONDS, missing)
    return _graph


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await get_graph()
    except Exception as e:  # MCP server not ready; retried on the first request
        log.warning("tools not loaded yet: %s", e)
    yield


app = FastAPI(title="Local AI agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class Step(BaseModel):
    tool: str
    args: dict
    result: str


class ChatResponse(BaseModel):
    thread_id: str
    answer: str
    steps: list[Step]
    seconds: float


def sources(context: str, answer: str) -> str:
    """A "Sources:" line for the retrieved passages, unless the answer already cites them.
    A 3B model often drops the citations it is asked for, so they're added here instead."""
    # "notes/a.md:3-9" or "scans/invoice.pdf p.2"
    refs = re.findall(r"^\[\d+\] (\S+(?::\d+-\d+| p\.\d+)) \(score", context, re.M)
    if not refs or any(r in answer for r in refs):
        return ""
    return "\n\nSources: " + ", ".join(dict.fromkeys(refs))


def web_sources(web: str, answer: str) -> str:
    """The links behind [1], [2] in a web answer: the model cites the numbers, not the URLs."""
    pages = re.findall(r"^\[(\d+)\] (.*)\n(https?://\S+)$", web, re.M)
    used = [(n, title, url) for n, title, url in pages if f"[{n}]" in answer and url not in answer]
    return ("\n\nSources:\n" + "\n".join(f"[{n}] {title} - {url}" for n, title, url in used)) if used else ""


@app.get("/health")
async def health():
    return {"status": "ok", "tools_loaded": _graph is not None, "servers_missing": _missing}


@app.get("/tools")
async def tools():
    try:
        await get_graph()
    except Exception as e:
        raise HTTPException(503, f"MCP servers unreachable: {e}")
    return {"model": LLM_MODEL, "servers_missing": _missing,
            "tools": [{"name": t.name, "description": t.description} for t in _tools]}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        graph = await get_graph()
    except Exception as e:
        raise HTTPException(503, f"MCP servers unreachable: {e}")

    thread_id = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 2 * MAX_STEPS + 1}
    start = time.time()
    try:
        result = await graph.ainvoke({"messages": [HumanMessage(req.message)]}, config)
    except Exception as e:
        log.exception("agent run failed")
        raise HTTPException(500, f"agent run failed: {e}")

    # Messages produced by this turn: everything after the last human message
    messages = result["messages"]
    last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    turn = messages[last_human + 1 :]

    results = {m.tool_call_id: text(m.content) for m in turn if isinstance(m, ToolMessage)}
    # The automatic steps come first, so the UI shows what the model was given
    auto = [(f"{MEMORY_TOOL} (auto)", {"query": req.message}, result.get("memories")),
            (f"{RETRIEVE_TOOL} (auto)", {"query": req.message}, result.get("context")),
            ("research (auto)", {"question": req.message}, result.get("web")),
            ("plan", {}, result.get("plan"))]
    steps = [Step(tool=name, args=args, result=res) for name, args, res in auto if res]
    steps += [
        Step(tool=c["name"], args=c["args"], result=results.get(c["id"], ""))
        for m in turn
        if isinstance(m, AIMessage)
        for c in m.tool_calls
    ]
    answer = text(turn[-1].content) if turn else ""
    answer += sources(result.get("context", ""), answer) + web_sources(result.get("web", ""), answer)
    seconds = round(time.time() - start, 1)
    log.info("thread %s: %d tool calls, %.1fs", thread_id, len(steps), seconds)
    return ChatResponse(thread_id=thread_id, answer=answer, steps=steps, seconds=seconds)

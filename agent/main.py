"""HTTP API for the agent (FastAPI, port 8000).

    POST /chat   {"message": "...", "thread_id": "optional"}
                 -> {"thread_id", "answer", "steps": [{"tool", "args", "result"}], "seconds"}
    GET  /tools  tools loaded from the MCP servers
    GET  /health liveness
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from graph import LLM_MODEL, MCP_SERVERS, build_graph, load_tools

log = logging.getLogger("agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Model + tool round trips per question; stops a small model from looping forever
MAX_STEPS = int(os.environ.get("MAX_STEPS", "12"))

_graph = None
_tools = []
_lock = asyncio.Lock()


async def get_graph():
    """Build the graph on first use, so the agent starts even if an MCP server isn't up yet."""
    global _graph, _tools
    async with _lock:
        if _graph is None:
            _tools = await load_tools()
            _graph = build_graph(_tools)
            log.info("loaded %d tools from %s: %s", len(_tools), list(MCP_SERVERS), [t.name for t in _tools])
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


def text(content) -> str:
    """Message content is a string or a list of content blocks; MCP tool results are the latter."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


@app.get("/health")
async def health():
    return {"status": "ok", "tools_loaded": _graph is not None}


@app.get("/tools")
async def tools():
    try:
        await get_graph()
    except Exception as e:
        raise HTTPException(503, f"MCP servers unreachable: {e}")
    return {"model": LLM_MODEL, "tools": [{"name": t.name, "description": t.description} for t in _tools]}


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
    steps = [
        Step(tool=c["name"], args=c["args"], result=results.get(c["id"], ""))
        for m in turn
        if isinstance(m, AIMessage)
        for c in m.tool_calls
    ]
    answer = text(turn[-1].content) if turn else ""
    seconds = round(time.time() - start, 1)
    log.info("thread %s: %d tool calls, %.1fs", thread_id, len(steps), seconds)
    return ChatResponse(thread_id=thread_id, answer=answer, steps=steps, seconds=seconds)

"""The agent graph: retrieve passages first, answer from them, fall back to a tool-calling loop.

Tools come from MCP servers (MCP_SERVERS), so adding a tool is a config change, not a code
change. The model is a LiteLLM alias (LLM_MODEL), never an Ollama model name.

    START -> retrieve --(passages?)--> answer --(answered)--> END
                 |                        |
                 |                    (NO_ANSWER)
                 v                        v
               agent --(tool calls?)--> tools -> agent ... --(no)--> END

Shaped around what a 3B model on CPU does reliably (qwen2.5:3b, measured 2026-10-03):
- `retrieve` runs the RAG search (RETRIEVE_TOOL) on every question. With tools bound, the model
  often skipped it, or searched again after being handed the passages.
- `answer` gets the passages and no tools: one short call (3–7 s) instead of two or three
  (12–40 s). When the passages don't answer the question it says NO_ANSWER and the question
  goes to `agent` without them.
- `agent` has the file tools (list_dir, read_file, search_files) for everything else. The search
  tool isn't offered to it; it only made redundant calls.
- "Which files..." questions skip retrieval: passages that mention files and folders made the
  model describe the README instead of listing the folder.
"""

import json
import os
import re
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://litellm.llm.svc.cluster.local:4000/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "chat-tools")
# {"<name>": {"url": "http://.../mcp"}, ...}; every server speaks MCP streamable HTTP
MCP_SERVERS = json.loads(
    os.environ.get(
        "MCP_SERVERS",
        '{"filesystem": {"url": "http://mcp-filesystem.agent.svc.cluster.local:8000/mcp"}}',
    )
)
# How many past messages (incl. tool results) go to the model; small models have small contexts
HISTORY_MESSAGES = int(os.environ.get("HISTORY_MESSAGES", "16"))
# Tool run on every question before the model; "" turns retrieval off
RETRIEVE_TOOL = os.environ.get("RETRIEVE_TOOL", "search_documents")
# Passages start with "[1] <file>:<lines>"; anything else ("No matching passages...") isn't context
PASSAGES_PREFIX = "[1] "
NO_ANSWER = "NO_ANSWER"
LIST_INTENT = re.compile(
    r"\b(which|what) (files|documents|notes|folders)\b|\blist\b.*\b(files|documents|notes|folders?)\b",
    re.IGNORECASE,
)

ANSWER_PROMPT = """Answer the user's question from these passages from their documents:

{passages}

Rules:
- Answer in two to four sentences or a short list, only with facts from the passages.
- If the passages do not answer the question, reply with exactly NO_ANSWER and nothing else."""

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")


async def load_tools():
    client = MultiServerMCPClient(
        {name: {"transport": "streamable_http", **cfg} for name, cfg in MCP_SERVERS.items()}
    )
    return await client.get_tools()


class State(MessagesState):
    context: str  # passages the current answer is based on ("" if none)


def text(content) -> str:
    """Message content is a string or a list of content blocks; MCP tool results are the latter."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


def build_graph(tools, model=None):
    """Compile the agent graph. `model` can be swapped for a fake in tests."""
    if model is None:
        model = ChatOpenAI(
            model=LLM_MODEL,
            base_url=LLM_BASE_URL,
            api_key="sk-local",  # LiteLLM runs without a key; the client needs a value
            temperature=0,
            timeout=600,  # 3B models on CPU are slow
        )
    search = next((t for t in tools if t.name == RETRIEVE_TOOL), None) if RETRIEVE_TOOL else None
    tools = [t for t in tools if t is not search]
    with_tools = model.bind_tools(tools)
    system = SystemMessage(SYSTEM_PROMPT)

    def history(state: State, plain: bool = False):
        # Keep the newest messages, starting on a user turn so no tool result loses its call
        msgs = trim_messages(state["messages"], max_tokens=HISTORY_MESSAGES, token_counter=len,
                             strategy="last", start_on="human")
        if plain:  # questions and final answers only, for a call without tools
            msgs = [m for m in msgs if isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and not m.tool_calls)]
        return msgs

    async def retrieve(state: State):
        question = text(next(m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)).content)
        if search is None or LIST_INTENT.search(question):
            return {"context": ""}
        try:
            found = text(await search.ainvoke({"query": question}))
        except Exception:  # RAG server down: answer without passages rather than fail
            return {"context": ""}
        return {"context": found if found.startswith(PASSAGES_PREFIX) else ""}

    async def answer(state: State):
        prompt = SystemMessage(ANSWER_PROMPT.format(passages=state["context"]))
        reply = await model.ainvoke([prompt, *history(state, plain=True)])
        if NO_ANSWER in text(reply.content) or not text(reply.content).strip():
            return {"context": ""}  # -> agent, without the passages
        return {"messages": [reply]}

    async def agent(state: State):
        reply = await with_tools.ainvoke([system, *history(state)])
        if not reply.tool_calls and not text(reply.content).strip():
            # With tools bound, qwen2.5:3b answers some plain questions ("17 times 23") with
            # nothing at all; the same call without tools answers them
            reply = await model.ainvoke([system, *history(state, plain=True)])
        return {"messages": [reply]}

    g = StateGraph(State)
    g.add_node("retrieve", retrieve)
    g.add_node("answer", answer)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    g.add_edge(START, "retrieve")
    g.add_conditional_edges("retrieve", lambda s: "answer" if s.get("context") else "agent", ["answer", "agent"])
    g.add_conditional_edges("answer", lambda s: END if s.get("context") else "agent", [END, "agent"])
    g.add_conditional_edges("agent", tools_condition)  # tool calls -> "tools", else END
    g.add_edge("tools", "agent")
    # Conversations live in memory, per thread_id; they are lost when the pod restarts
    return g.compile(checkpointer=InMemorySaver())

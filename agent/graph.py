"""The agent graph: route the question, look things up first, answer, fall back to a tool loop.

Tools come from MCP servers (MCP_SERVERS), so adding a tool is a config change, not a code
change. The model is a LiteLLM alias (LLM_MODEL), never an Ollama model name.

    START --"remember/forget ..."--> memorize ----------------------------------> END
      |---"look it up online"-----> research --> summarise ---------------------> END
      v
    prepare (memories; passages) --(passages or facts?)--> answer --(answered)--> END
      |                                                     | (NO_ANSWER)
      +-----------------------------------------------------+--> agent --(tool calls?)--> tools
                                                                   ^-----------------------+

Shaped around what a 3B model on CPU does reliably (qwen2.5:3b, measured 2026-10-03/08):
- Fixed steps run without the model where a rule is enough. `prepare` runs the RAG search
  (RETRIEVE_TOOL) and looks up saved facts (MEMORY_TOOL) on every question; "remember that ..."
  is stored directly; a web question runs the one `research` tool. With tools bound, the model
  often skipped a step, or repeated one after being handed its result.
- `answer` and `summarise` get the material and no tools: one short call instead of two or
  three round trips. When the material doesn't answer the question, `answer` says NO_ANSWER and
  the question goes to `agent` without it.
- `agent` has the remaining tools (files, spam check, calendar, web). The search tool isn't
  offered to it; it only made redundant calls.
- Multi-step requests ("A and then B") are split into their parts (split_request), and main.py
  runs each part through this graph in turn. Asked to plan, the 3B model listed tools almost at
  random ("list_dir, search_documents, add_event, list_events") and, pushed to finish that plan,
  once added a calendar event nobody asked for (golden set, 2026-10-08).
- Questions that need a tool skip retrieval (TOOL_INTENT): "which files..." (passages that
  mention files made the model describe the README instead of listing the folder), "is this
  spam...", and calendar questions.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
# Saved facts looked up on every question (memory MCP server); "" turns it off
MEMORY_TOOL = os.environ.get("MEMORY_TOOL", "recall")
# The dates in prompts ("today is ...") are in this time zone
TZ = ZoneInfo(os.environ.get("AGENT_TZ", "Asia/Dubai"))
# Passages start with "[1] <file>:<lines>"; anything else ("No matching passages...") isn't context
PASSAGES_PREFIX = "[1] "
NO_ANSWER = "NO_ANSWER"
# Questions that need a tool, not the documents: which files exist (list_dir), whether a
# message is spam (classify_message), and the calendar. Passages would only get in the way.
TOOL_INTENT = re.compile(
    r"\b(which|what) (files|documents|notes|folders)\b|\blist\b.*\b(files|documents|notes|folders?)\b"
    r"|\b(spam|scam|phishing|junk)\b|\bclassify\b"
    r"|\b(calendar|agenda|appointments?|schedule)\b|\bwhat'?s on (today|tomorrow|this week|next week)\b"
    r"|\b(am i|are we) (free|busy)\b|\bwhat (time|day|date) is it\b|\btoday'?s date\b"
    r"|\b(add|book|put|create|set up|schedule)\b.{0,40}\b(meeting|call|event|appointment|reminder|lunch|dinner)\b",
    re.IGNORECASE,
)
# "remember that ..." / "forget that ...": stored or deleted directly (memory MCP server)
REMEMBER = re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?[\s:,]+(?P<fact>.+?)\s*$", re.IGNORECASE | re.DOTALL)
FORGET = re.compile(r"^\s*(?:please\s+)?forget(?:\s+that)?[\s:,]+(?P<fact>.+?)\s*$", re.IGNORECASE | re.DOTALL)
# Questions for the web (web MCP server's `research`)
RESEARCH_INTENT = re.compile(
    r"\b(search|look (it |this |that )?up|google|find)\b.{0,60}\b(web|online|internet)\b"
    r"|\b(on|from) the (web|internet)\b|^\s*(please\s+)?research\b|\blatest news\b|\bnews (about|on)\b",
    re.IGNORECASE,
)
# Where a request with several steps divides: "list my files and then read the to-do list"
STEP_BREAK = re.compile(r"\s*[,;.]?\s*\b(?:and then|then|after that|afterwards|and also)\b[,:]?\s*", re.IGNORECASE)
MAX_STEPS_PER_REQUEST = 4

ANSWER_PROMPT = """Answer the user's question from this material:

{material}

Rules:
- Answer in two to four sentences or a short list, only with facts from the material.
- If the material does not answer the question, reply with exactly NO_ANSWER and nothing else."""

SUMMARISE_PROMPT = """Answer the user's question from these web pages:

{pages}

Rules:
- Three to six sentences, or a short list; only facts from the pages.
- Cite the pages you used as [1], [2] after the sentence.
- If the pages don't answer it, say what they do say and that it's not conclusive."""

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")


def split_request(message: str) -> list[str]:
    """The parts of a multi-step request, in order; one part if it isn't one. A part needs two
    words or more ("what then?" stays whole), and a leading "first" is dropped."""
    parts = [re.sub(r"^(first|firstly)[,:]?\s+", "", p.strip(" ,;."), flags=re.IGNORECASE)
             for p in STEP_BREAK.split(message)]
    parts = [p for p in parts if len(p.split()) >= 2]
    if len(parts) < 2:
        return [message]
    return parts[: MAX_STEPS_PER_REQUEST - 1] + [" and then ".join(parts[MAX_STEPS_PER_REQUEST - 1:])] \
        if len(parts) > MAX_STEPS_PER_REQUEST else parts


async def load_tools() -> tuple[list, list[str]]:
    """Tools of every reachable MCP server, and the names of the servers that weren't reachable."""
    client = MultiServerMCPClient(
        {name: {"transport": "streamable_http", **cfg} for name, cfg in MCP_SERVERS.items()}
    )
    tools, missing = [], []
    for name in MCP_SERVERS:
        try:
            tools += await client.get_tools(server_name=name)
        except Exception:
            missing.append(name)
    if not tools and missing:
        raise ConnectionError(f"no MCP server reachable ({', '.join(missing)})")
    return tools, missing


class State(MessagesState):
    context: str  # passages the current answer is based on ("" if none)
    memories: str  # saved facts that relate to the question ("" if none)
    web: str  # web excerpts the answer is based on ("" if none)
    answered: bool  # `answer` replied from the material (else the question goes to `agent`)


def text(content) -> str:
    """Message content is a string or a list of content blocks; MCP tool results are the latter."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


def today() -> str:
    n = datetime.now(TZ)
    return f"Today is {n:%A %d %B %Y}, {n:%H:%M} ({TZ.key})."


def build_graph(tools, model=None, checkpointer=None):
    """Compile the agent graph. `model` can be swapped for a fake in tests; `checkpointer`
    keeps conversations (main.py passes a SQLite one so they survive restarts)."""
    if model is None:
        model = ChatOpenAI(
            model=LLM_MODEL,
            base_url=LLM_BASE_URL,
            api_key="sk-local",  # LiteLLM runs without a key; the client needs a value
            temperature=0,
            timeout=600,  # 3B models on CPU are slow
        )
    by_name = {t.name: t for t in tools}
    search = by_name.get(RETRIEVE_TOOL) if RETRIEVE_TOOL else None
    recall = by_name.get(MEMORY_TOOL) if MEMORY_TOOL else None
    remember, forget, research = by_name.get("remember"), by_name.get("forget"), by_name.get("research")
    # The agent gets everything but the steps that run on their own
    automatic = {n for n in (RETRIEVE_TOOL, MEMORY_TOOL, "remember", "forget") if n}
    agent_tools = [t for t in tools if t.name not in automatic]
    with_tools = model.bind_tools(agent_tools)

    def system(state: State) -> SystemMessage:
        extra = [today()]
        if state.get("memories"):
            extra.append("What you know about the user from earlier conversations:\n" + state["memories"])
        return SystemMessage(SYSTEM_PROMPT + "\n\n" + "\n\n".join(extra))

    def question(state: State) -> str:
        return text(next(m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)).content)

    def history(state: State, plain: bool = False):
        # Keep the newest messages, starting on a user turn so no tool result loses its call
        msgs = trim_messages(state["messages"], max_tokens=HISTORY_MESSAGES, token_counter=len,
                             strategy="last", start_on="human")
        if plain:  # questions and final answers only, for a call without tools
            msgs = [m for m in msgs if isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and not m.tool_calls)]
        return msgs

    async def call(tool, args) -> str:
        try:
            return text(await tool.ainvoke(args))
        except Exception as e:  # a server that's down shouldn't fail the whole answer
            return f"{tool.name} failed: {e}"

    def route(state: State) -> str:
        q = question(state)
        if (remember and REMEMBER.match(q)) or (forget and FORGET.match(q)):
            return "memorize"
        if research and RESEARCH_INTENT.search(q):
            return "research"
        return "prepare"

    async def memorize(state: State):
        q = question(state)
        m = REMEMBER.match(q) if remember else None
        result = await call(remember, {"fact": m["fact"]}) if m else await call(forget, {"what": FORGET.match(q)["fact"]})
        reply = result.replace("Remembered:", "Got it, I'll remember:").replace("Forgot:", "Done, I've forgotten:")
        return {"messages": [AIMessage(reply)], "context": "", "memories": "", "web": ""}

    async def research_node(state: State):
        return {"web": await call(research, {"question": question(state)}), "context": "", "memories": ""}

    async def summarise(state: State):
        if not state["web"].startswith("[1] "):  # off, failed or nothing found: say so as it is
            return {"messages": [AIMessage(state["web"])]}
        prompt = SystemMessage(today() + "\n\n" + SUMMARISE_PROMPT.format(pages=state["web"]))
        return {"messages": [await model.ainvoke([prompt, *history(state, plain=True)])]}

    async def prepare(state: State):
        q = question(state)
        update = {"context": "", "memories": "", "web": "", "answered": False}
        if recall:
            found = await call(recall, {"query": q})
            update["memories"] = found if found.startswith("#") else ""
        if search and not TOOL_INTENT.search(q):
            found = await call(search, {"query": q})
            update["context"] = found if found.startswith(PASSAGES_PREFIX) else ""
        return update

    def after_prepare(state: State) -> str:
        if state.get("context"):
            return "answer"
        # A saved fact may answer it outright ("who is my manager?"): one call, no tools
        return "answer" if state.get("memories") and not TOOL_INTENT.search(question(state)) else "agent"

    async def answer(state: State):
        material = []
        if state.get("context"):
            material.append("Passages from the user's documents:\n" + state["context"])
        if state.get("memories"):
            material.append("Facts the user told you in earlier conversations:\n" + state["memories"])
        prompt = SystemMessage(today() + "\n\n" + ANSWER_PROMPT.format(material="\n\n".join(material)))
        reply = await model.ainvoke([prompt, *history(state, plain=True)])
        if NO_ANSWER in text(reply.content) or not text(reply.content).strip():
            return {"context": "", "answered": False}  # -> agent, without the passages
        return {"messages": [reply], "answered": True}

    async def agent(state: State):
        reply = await with_tools.ainvoke([system(state), *history(state)])
        if not reply.tool_calls and not text(reply.content).strip():
            # With tools bound, qwen2.5:3b answers some plain questions ("17 times 23") with
            # nothing at all; the same call without tools answers them
            reply = await model.ainvoke([system(state), *history(state, plain=True)])
        return {"messages": [reply]}

    g = StateGraph(State)
    g.add_node("memorize", memorize)
    g.add_node("research", research_node)
    g.add_node("summarise", summarise)
    g.add_node("prepare", prepare)
    g.add_node("answer", answer)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(agent_tools, handle_tool_errors=True))
    g.add_conditional_edges(START, route, ["memorize", "research", "prepare"])
    g.add_edge("memorize", END)
    g.add_edge("research", "summarise")
    g.add_edge("summarise", END)
    g.add_conditional_edges("prepare", after_prepare, ["answer", "agent"])
    g.add_conditional_edges("answer", lambda s: END if s.get("answered") else "agent", [END, "agent"])
    g.add_conditional_edges("agent", tools_condition)  # tool calls -> "tools", else END
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer or InMemorySaver())

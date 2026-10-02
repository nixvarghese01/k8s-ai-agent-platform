"""The agent graph: a LangGraph loop of model -> tools -> model until the model answers.

Tools come from MCP servers (MCP_SERVERS), so adding a tool is a config change, not a code
change. The model is a LiteLLM alias (LLM_MODEL), never an Ollama model name.

    START -> agent --(tool calls?)--> tools -> agent ... --(no)--> END
"""

import json
import os
from pathlib import Path

from langchain_core.messages import SystemMessage, trim_messages
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
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

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")


async def load_tools():
    client = MultiServerMCPClient(
        {name: {"transport": "streamable_http", **cfg} for name, cfg in MCP_SERVERS.items()}
    )
    return await client.get_tools()


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
    model = model.bind_tools(tools)
    system = SystemMessage(SYSTEM_PROMPT)

    async def agent(state: MessagesState):
        # Keep the newest messages, starting on a user turn so no tool result loses its call
        history = trim_messages(
            state["messages"],
            max_tokens=HISTORY_MESSAGES,
            token_counter=len,
            strategy="last",
            start_on="human",
        )
        return {"messages": [await model.ainvoke([system, *history])]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)  # tool calls -> "tools", else END
    g.add_edge("tools", "agent")
    # Conversations live in memory, per thread_id; they are lost when the pod restarts
    return g.compile(checkpointer=InMemorySaver())

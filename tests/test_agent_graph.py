"""The agent loop with a scripted model: it calls a tool, gets the result, then answers."""

import asyncio

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from graph import build_graph


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@tool
def list_dir(path: str = ".") -> str:
    """List a folder."""
    return "file README.md (10 bytes)"


def test_tool_loop():
    model = FakeToolModel(
        messages=iter(
            [
                AIMessage("", tool_calls=[{"name": "list_dir", "args": {"path": "."}, "id": "c1"}]),
                AIMessage("There is one file: README.md"),
            ]
        )
    )
    graph = build_graph([list_dir], model=model)
    config = {"configurable": {"thread_id": "t1"}}
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage("what files?")]}, config))

    kinds = [type(m) for m in result["messages"]]
    assert kinds == [HumanMessage, AIMessage, ToolMessage, AIMessage]
    assert result["messages"][2].content == "file README.md (10 bytes)"
    assert result["messages"][-1].content == "There is one file: README.md"


def test_text_flattens_content_blocks():
    from main import text

    assert text("plain") == "plain"
    assert text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"

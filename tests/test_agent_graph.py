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


class RecordingModel(FakeToolModel):
    """Remembers the messages of every call."""

    seen: list = []

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def run(tools, answers, question):
    model = RecordingModel(messages=iter(answers), seen=[])
    graph = build_graph(tools, model=model)
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(question)]}, {"configurable": {"thread_id": "t"}}))
    return model, result


PASSAGE = "[1] notes/meeting.md:1-4 (score 0.70)\nWe decided to buy a cooling stand."


def searcher(result: str, calls: list | None = None):
    @tool
    def search_documents(query: str) -> str:
        """Search."""
        if calls is not None:
            calls.append(query)
        return result

    return search_documents


def test_matching_passages_are_answered_in_one_call_without_tools():
    model, result = run([searcher(PASSAGE), list_dir], [AIMessage("A cooling stand.")], "What did we decide?")
    assert len(model.seen) == 1  # no tool round trip
    prompt, question = model.seen[0]
    assert "notes/meeting.md:1-4" in prompt.content and "NO_ANSWER" in prompt.content
    assert question.content == "What did we decide?"
    assert result["context"].startswith("[1] ") and result["messages"][-1].content == "A cooling stand."


def test_no_answer_falls_back_to_the_tool_loop_without_passages():
    answers = [
        AIMessage("NO_ANSWER"),
        AIMessage("", tool_calls=[{"name": "list_dir", "args": {"path": "."}, "id": "c1"}]),
        AIMessage("There is one file: README.md"),
    ]
    model, result = run([searcher(PASSAGE), list_dir], answers, "What did we decide?")
    assert len(model.seen) == 3
    assert "Answer the user's question" not in model.seen[1][0].content  # agent prompt, no passages
    assert result["context"] == ""
    assert result["messages"][-1].content == "There is one file: README.md"


def test_no_passages_goes_straight_to_the_agent():
    model, result = run([searcher("No matching passages.")], [AIMessage("Paris.")], "Capital of France?")
    assert len(model.seen) == 1 and result["context"] == ""
    assert "list_dir(path)" in model.seen[0][0].content  # the agent's system prompt


def test_which_files_questions_skip_retrieval():
    calls = []
    run([searcher(PASSAGE, calls), list_dir], [AIMessage("README.md")], "What files are in my shared folder?")
    run([searcher(PASSAGE, calls), list_dir], [AIMessage("README.md")], "List my notes")
    run([searcher(PASSAGE, calls), list_dir], [AIMessage("Milk.")], "What's on my todo list?")
    assert calls == ["What's on my todo list?"]


def test_empty_reply_with_tools_is_retried_without():
    model, result = run([list_dir], [AIMessage(""), AIMessage("391")], "What is 17 times 23?")
    assert len(model.seen) == 2 and result["messages"][-1].content == "391"


def test_sources_line_added_only_when_answer_lacks_citations():
    from main import sources

    ctx = "[1] notes/a.md:1-4 (score 0.70)\nText.\n\n[2] docs/b.md:9-12 (score 0.68)\nMore."
    assert sources(ctx, "The answer.") == "\n\nSources: notes/a.md:1-4, docs/b.md:9-12"
    assert sources(ctx, "The answer (notes/a.md:1-4).") == ""
    assert sources("", "Paris.") == ""

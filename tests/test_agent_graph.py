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


def test_spam_questions_go_to_the_tools_not_the_documents():
    calls = []
    run([searcher(PASSAGE, calls), list_dir], [AIMessage("SPAM")], "Is this spam: 'You won a prize, call now'?")
    run([searcher(PASSAGE, calls), list_dir], [AIMessage("ok")], "Classify this message: hi mum")
    assert calls == []


# ---- workflows 1, 5, 6: memory, calendar, web research --------------------------------------
def memory_tools(saved: list, facts: str = "#1 I live in Dubai (saved 2026-10-08)"):
    @tool
    def remember(fact: str) -> str:
        """Save a fact."""
        saved.append(fact)
        return f"Remembered: {fact}"

    @tool
    def forget(what: str) -> str:
        """Delete a fact."""
        saved.append(f"-{what}")
        return f"Forgot: {what}"

    @tool
    def recall(query: str = "") -> str:
        """Look up facts."""
        return facts

    return [remember, forget, recall]


def test_remember_and_forget_are_stored_without_the_model():
    saved = []
    model, result = run(memory_tools(saved), [], "Remember that my gym renews on 1 November")
    assert saved == ["my gym renews on 1 November"] and model.seen == []
    assert result["messages"][-1].content == "Got it, I'll remember: my gym renews on 1 November"
    model, result = run(memory_tools(saved), [], "please forget that my gym renews")
    assert saved[-1] == "-my gym renews" and result["messages"][-1].content.startswith("Done, I've forgotten")


def test_saved_facts_reach_the_model_with_todays_date():
    model, result = run([*memory_tools([]), list_dir], [AIMessage("In Dubai.")], "Where do I live?")
    system = model.seen[0][0].content
    assert "I live in Dubai" in system and "Today is " in system
    assert result["memories"].startswith("#1")


def test_calendar_questions_skip_the_documents():
    calls = []
    for q in ("What's on my calendar tomorrow?", "Am I free on Friday afternoon?", "Add a meeting with Maria tomorrow 3pm",
              "What day is it?"):
        run([searcher(PASSAGE, calls), list_dir], [AIMessage("ok")], q)
    assert calls == []


def test_web_questions_run_research_then_one_summary_call():
    asked = []

    @tool
    def research(question: str) -> str:
        """Research the web."""
        asked.append(question)
        return "[1] Release notes\nhttps://example.com/v2\nVersion 2 is out."

    model, result = run([research, list_dir], [AIMessage("Version 2 is out [1].")], "Search the web for the latest release")
    assert asked == ["Search the web for the latest release"] and len(model.seen) == 1
    assert "https://example.com/v2" in model.seen[0][0].content and "[1]" in model.seen[0][0].content
    from main import web_sources

    assert web_sources(result["web"], "Version 2 is out [1].") == "\n\nSources:\n[1] Release notes - https://example.com/v2"


def test_research_off_is_reported_as_is():
    @tool
    def research(question: str) -> str:
        """Research the web."""
        return "Web search isn't running: it's part of the research profile."

    model, result = run([research], [], "look this up online: weather")
    assert model.seen == [] and "research profile" in result["messages"][-1].content


def test_load_tools_skips_servers_that_are_down(monkeypatch):
    import graph

    class Client:
        def __init__(self, servers):
            pass

        async def get_tools(self, server_name):
            if server_name == "down":
                raise ConnectionError("refused")
            return [list_dir]

    monkeypatch.setattr(graph, "MultiServerMCPClient", Client)
    monkeypatch.setattr(graph, "MCP_SERVERS", {"up": {"url": "u"}, "down": {"url": "d"}})
    tools, missing = asyncio.run(graph.load_tools())
    assert [t.name for t in tools] == ["list_dir"] and missing == ["down"]


# ---- multi-step requests: split, then each part on its own --------------------------------
def test_split_request():
    from graph import split_request

    assert split_request("List my files and then tell me what my to-do list says") == [
        "List my files", "tell me what my to-do list says"]
    assert split_request("First read the meeting note, then add a reminder, after that list my files") == [
        "read the meeting note", "add a reminder", "list my files"]
    assert split_request("What happened then?") == ["What happened then?"]  # nothing to split
    assert split_request("What did we decide?") == ["What did we decide?"]
    many = split_request("do a b and then do c d and then do e f and then do g h and then do i j")
    assert len(many) == 4 and many[-1] == "do g h and then do i j"


def test_each_part_is_answered_in_turn_in_one_conversation(monkeypatch):
    import main

    answers = [AIMessage("", tool_calls=[{"name": "list_dir", "args": {"path": "."}, "id": "c1"}]),
               AIMessage("One file: README.md."), AIMessage("The to-do list says: buy milk.")]
    model = RecordingModel(messages=iter(answers), seen=[])
    graph = build_graph([list_dir], model=model)

    async def fake_graph():
        return graph

    monkeypatch.setattr(main, "get_graph", fake_graph)
    r = asyncio.run(main.chat(main.ChatRequest(message="List my files and then tell me what my to-do list says",
                                               thread_id="t")))
    assert [s.tool for s in r.steps] == ["plan", "list_dir"]
    assert r.steps[0].result == "1. List my files\n2. tell me what my to-do list says"
    assert r.answer == ("**List my files**\n\nOne file: README.md.\n\n"
                        "**tell me what my to-do list says**\n\nThe to-do list says: buy milk.")
    assert model.seen[-1][-1].content == "tell me what my to-do list says"  # the 2nd part, with the 1st in history

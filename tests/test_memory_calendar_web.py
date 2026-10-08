"""Workflows 1, 5 and 6: the memory, calendar and web MCP servers, without a cluster or network."""

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest

import calendar_server as cal
import memory_server as mem
import web_server as web


# ---- memory --------------------------------------------------------------------------------
@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "DB", str(tmp_path / "memory.sqlite"))


def test_remember_recall_forget(memory):
    assert mem.remember("my gym membership renews on 1 November.") == "Remembered: My gym membership renews on 1 November"
    assert mem.remember("My gym membership renews on 1 November").startswith("Already remembered")
    mem.remember("I live in Dubai")
    mem.remember("My manager is Maria")

    assert "Dubai" in mem.recall("where do I live?") and "gym" not in mem.recall("where do I live?")
    assert "gym membership" in mem.recall("when does the gym renew")
    assert mem.recall("quantum physics") == "No saved facts match."
    assert mem.recall("").count("#") == 3  # "" lists the newest

    assert mem.forget("manager") == "Forgot: My manager is Maria"
    assert mem.forget("#1").startswith("Forgot: My gym")
    assert mem.forget("#99") == "No saved fact matches '#99'."
    assert mem.recall("").count("#") == 1


def test_stemming_matches_word_forms():
    assert mem.words("I lived there; meetings") == mem.words("living there meeting")


# ---- calendar ------------------------------------------------------------------------------
BASE = datetime(2026, 10, 8, 10, 0, tzinfo=cal.TZ)  # a Thursday


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "CAL_DIR", tmp_path)
    monkeypatch.setattr(cal, "OWN", tmp_path / "agent.ics")
    monkeypatch.setattr(cal, "ICS_URLS", [])
    monkeypatch.setattr(cal, "now", lambda: BASE)
    return tmp_path


@pytest.mark.parametrize(
    "text, expected",
    [
        ("today", "2026-10-08"),
        ("tomorrow", "2026-10-09"),
        ("friday", "2026-10-09"),
        ("thursday", "2026-10-08"),  # today, not a week ago
        ("next thursday", "2026-10-15"),
        ("monday 9:30", "2026-10-12 09:30"),
        ("2026-10-20 14:00", "2026-10-20 14:00"),
    ],
)
def test_parse_when(text, expected, calendar):
    got = cal.parse_when(text, BASE)
    assert got.strftime("%Y-%m-%d %H:%M" if " " in expected else "%Y-%m-%d") == expected


def test_add_then_list_with_overlap_warning(calendar):
    out = cal.add_event("Design review", "friday 3pm", 60, "Room 2")
    assert out.startswith("Added: Design review, Friday 09 October 2026 15:00-16:00 @ Room 2")
    assert (calendar / "agent.ics").exists()
    assert "overlaps Fri 09 Oct 15:00-16:00: Design review" in cal.add_event("Dentist", "friday 15:30", 30)

    listing = cal.list_events("friday")
    assert "15:00-16:00: Design review @ Room 2" in listing and "15:30-16:00: Dentist" in listing
    assert cal.list_events("today") == "No events Thursday 08 October 2026."
    assert "Design review" in cal.list_events("this week")  # a week from today


def test_date_without_time_starts_at_nine(calendar):
    assert "09:00-10:00" in cal.add_event("Car service", "2026-10-13")


def test_exported_calendar_with_a_weekly_event(calendar):
    (calendar / "work.ics").write_text(
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:test\nBEGIN:VEVENT\nUID:1\nSUMMARY:Team standup\n"
        "DTSTART;TZID=Asia/Dubai:20261001T091500\nDTEND;TZID=Asia/Dubai:20261001T093000\n"
        "RRULE:FREQ=WEEKLY;BYDAY=TH\nEND:VEVENT\nBEGIN:VEVENT\nUID:2\nSUMMARY:Holiday\n"
        "DTSTART;VALUE=DATE:20261015\nDTEND;VALUE=DATE:20261016\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    assert "Thu 08 Oct 09:15-09:30: Team standup" in cal.list_events("today")
    week = cal.list_events("next week")
    assert "Thu 15 Oct, all day: Holiday" in week and "Thu 15 Oct 09:15-09:30: Team standup" in week


# ---- web -----------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://10.43.0.1/", "http://169.254.169.254/latest/",
                                 "http://localhost:8080/", "file:///etc/passwd", "ftp://example.com/"])
def test_private_and_odd_urls_are_refused(url):
    with pytest.raises(web.Blocked):
        web.check_public(url)


def test_fetch_extracts_text_and_checks_every_redirect(monkeypatch):
    checked = []
    monkeypatch.setattr(web, "check_public", checked.append)
    article = "<html><body><nav>Home | About</nav><article><h1>Release</h1>" + "<p>Version 2 ships faster search for everyone. </p>" * 20 + "</article></body></html>"

    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text=article, headers={"content-type": "text/html"})

    real = httpx.AsyncClient
    monkeypatch.setattr(web.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    text = asyncio.run(web.fetch("https://example.com/old", 300))
    assert checked == ["https://example.com/old", "https://example.com/new"]
    assert text.startswith("Version 2 ships faster search") or "Version 2 ships" in text
    assert "Home | About" not in text and len(text) <= 300


def test_research_numbers_pages_and_reports_when_search_is_off(monkeypatch):
    async def search(q, n=5):
        return [{"title": "A", "url": "https://a.example/", "snippet": "sa"},
                {"title": "B", "url": "https://b.example/", "snippet": "sb"}]

    async def fetch(url, max_chars):
        if "b." in url:
            raise web.Blocked("no")
        return "Text of A."

    monkeypatch.setattr(web, "search", search)
    monkeypatch.setattr(web, "fetch", fetch)
    out = asyncio.run(web.research("what is new?", 2))
    assert out == "[1] A\nhttps://a.example/\nText of A.\n\n[2] B\nhttps://b.example/\nsb"

    async def down(q, n=5):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(web, "search", down)
    assert asyncio.run(web.research("x")) == web.OFF


def test_search_parses_searxng_json(monkeypatch):
    payload = {"results": [{"title": " One ", "url": "https://one/", "content": "first  hit"},
                           {"title": "Dup", "url": "https://one/", "content": "again"},
                           {"title": "Two", "url": "https://two/", "content": ""}]}
    real = httpx.AsyncClient
    monkeypatch.setattr(web.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)), **kw))
    assert asyncio.run(web.search("q")) == [{"title": "One", "url": "https://one/", "snippet": "first hit"},
                                            {"title": "Two", "url": "https://two/", "snippet": ""}]

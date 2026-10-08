"""Memory MCP server (workflow 1): facts the agent keeps across conversations.

"Remember that my gym is on Tuesdays" stores a fact; the agent looks up the relevant ones on
every question, so the answer can use them days later. Facts live in SQLite on a volume
(MEMORY_DB), so they survive restarts. Matching is by shared words, not embeddings: a few
hundred personal facts don't need a vector search, and this answers in milliseconds.

    remember(fact)      store a fact (an exact repeat is not stored twice)
    recall(query)       the facts that share words with the query; "" lists the newest
    forget(what)        delete fact #N, or the fact that best matches the words
Served over MCP streamable HTTP at http://<host>:8000/mcp, like the other MCP servers.
"""

import os
import re
import sqlite3
import time
from contextlib import closing

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

DB = os.environ.get("MEMORY_DB", "/data/memory.sqlite")
MAX_FACT_CHARS = 500

STOPWORDS = set(
    "a an the and or but if of to in on at for with from by about as is are was were be been am do does did "
    "i me my mine we our you your he she it they them their this that these those what which who whom whose "
    "when where why how can could would should will shall may might must have has had not no yes please "
    "remember forget know tell there here any some all just also very so than then too".split()
)

mcp = FastMCP(
    "memory",
    instructions="Long-term memory: facts about the user that last across conversations.",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, fact TEXT NOT NULL UNIQUE, created REAL NOT NULL)")
    return conn


def stem(w: str) -> str:
    """Crude suffix stripping: meetings/meeting/meet, lives/lived/living/live all meet."""
    for _ in range(2):
        if len(w) > 4:
            w = re.sub(r"(ing|ed|es|s)$", "", w)
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


def words(text: str) -> set[str]:
    """Content words of a text, stemmed, without the small words every sentence has."""
    return {stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1}


def clean(fact: str) -> str:
    fact = re.sub(r"\s+", " ", fact).strip().rstrip(".")
    return fact[:1].upper() + fact[1:MAX_FACT_CHARS] if fact else ""


def matches(query: str, limit: int) -> list[tuple[int, str, float]]:
    with closing(db()) as conn:
        rows = conn.execute("SELECT id, fact, created FROM facts ORDER BY created DESC").fetchall()
    if not query.strip():
        return rows[:limit]
    q = words(query)
    scored = [(len(q & words(fact)), created, (i, fact, created)) for i, fact, created in rows]
    return [row for score, _, row in sorted(scored, reverse=True) if score > 0][:limit]


def show(rows) -> str:
    return "\n".join(f"#{i} {fact} (saved {time.strftime('%Y-%m-%d', time.localtime(created))})" for i, fact, created in rows)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    with closing(db()):
        return PlainTextResponse("ok")


@mcp.tool()
def remember(fact: str) -> str:
    """Save a fact about the user for later conversations, e.g. "My gym membership renews on 1 November".

    Pass the fact as a short sentence in the third or first person, without "remember that".
    """
    fact = clean(fact)
    if not fact:
        return "Nothing to remember: the fact was empty."
    with closing(db()) as conn, conn:
        cur = conn.execute("INSERT OR IGNORE INTO facts (fact, created) VALUES (?, ?)", (fact, time.time()))
    return f"Remembered: {fact}" if cur.rowcount else f"Already remembered: {fact}"


@mcp.tool()
def recall(query: str = "", limit: int = 8) -> str:
    """Look up saved facts about the user that relate to the query ("" lists the newest ones)."""
    rows = matches(query, max(1, min(limit, 50)))
    return show(rows) if rows else "No saved facts match."


@mcp.tool()
def forget(what: str) -> str:
    """Delete a saved fact: its number ("#3") or words from it ("gym membership")."""
    m = re.fullmatch(r"\s*#?(\d+)\s*", what)
    with closing(db()) as conn, conn:
        if m:
            row = conn.execute("SELECT id, fact FROM facts WHERE id = ?", (int(m.group(1)),)).fetchone()
        else:
            best = matches(what, 1)
            row = best[0][:2] if best else None
        if not row:
            return f"No saved fact matches {what!r}."
        conn.execute("DELETE FROM facts WHERE id = ?", (row[0],))
    return f"Forgot: {row[1]}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

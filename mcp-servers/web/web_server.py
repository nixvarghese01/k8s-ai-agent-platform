"""Web research MCP server (workflow 6): search the web and read pages, with their links.

Search goes through SearXNG, a self-hosted metasearch engine (profile `research`): no API key,
no account, and the search engines see SearXNG, not the user's browser. Pages are fetched here
and reduced to their main text (trafilatura), so the model gets an article, not menus and ads.

    web_search(query)     titles, links and snippets
    fetch_page(url)       the readable text of one page
    research(question)    search + read the top pages in one step: excerpts with numbered links,
                          which is what a 3B model handles best (one tool call, not five)
Plain HTTP for n8n's daily briefing: GET /headlines?q=...&n=5 -> {"text": ..., "results": [...]}.

Only public addresses are fetched: the agent could be talked into "reading" an internal URL
(a cluster service, the router, cloud metadata), so private, loopback and link-local targets
are refused, at every redirect.
"""

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng.agent.svc.cluster.local:8080")
MAX_PAGE_BYTES = 2_000_000
EXCERPT_CHARS = int(os.environ.get("EXCERPT_CHARS", "1500"))
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) local-ai-platform research"
OFF = ("Web search isn't running: it's part of the research profile. "
       "Start it with `.\\local-up -Profile research` (or `make profile P=research`) and ask again.")

mcp = FastMCP(
    "web",
    instructions="Search the web and read web pages; answers come with their links.",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
)


class Blocked(Exception):
    pass


def check_public(url: str) -> None:
    """Refuse anything but http(s) to a public address."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise Blocked(f"only http(s) links can be read, not {url!r}")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise Blocked(f"{u.hostname} doesn't resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise Blocked(f"{u.hostname} is a private or local address; only public sites can be read")


async def search(query: str, n: int = 5) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{SEARXNG_URL}/search", params={"q": query, "format": "json", "safesearch": 1})
        r.raise_for_status()
    results = []
    for item in r.json().get("results", []):
        if item.get("url") and item["url"] not in {x["url"] for x in results}:
            results.append({"title": item.get("title", "").strip(), "url": item["url"],
                            "snippet": " ".join(item.get("content", "").split())[:300]})
        if len(results) >= n:
            break
    return results


async def fetch(url: str, max_chars: int) -> str:
    """The main text of a page, following redirects by hand so each hop is checked."""
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(5):
            await asyncio.to_thread(check_public, url)
            async with client.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers["location"])
                    continue
                r.raise_for_status()
                kind = r.headers.get("content-type", "")
                if "html" not in kind and "text" not in kind:
                    raise Blocked(f"not a web page ({kind or 'unknown type'})")
                body = b""
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_PAGE_BYTES:
                        break
                break
        else:
            raise Blocked("too many redirects")
    html = body.decode(r.encoding or "utf-8", errors="replace")
    text = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True) or ""
    if not text and "html" not in kind:
        text = html
    return " ".join(text.split())[:max_chars]


def numbered(results: list[dict]) -> str:
    return "\n\n".join(f"[{i}] {r['title']}\n{r['url']}\n{r['snippet']}" for i, r in enumerate(results, 1))


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")  # healthy even when SearXNG is off; the tools say so


@mcp.custom_route("/headlines", methods=["GET"])
async def headlines(request: Request) -> JSONResponse:
    q = request.query_params.get("q", "technology news")
    try:
        results = await search(q, int(request.query_params.get("n", "5")))
    except httpx.HTTPError:
        return JSONResponse({"text": OFF, "results": []})
    return JSONResponse({"text": "\n".join(f"- [{r['title']}]({r['url']})" for r in results) or "Nothing found.",
                         "results": results})


@mcp.tool()
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web. Returns numbered results with title, link and a short snippet."""
    try:
        results = await search(query, max(1, min(max_results, 10)))
    except httpx.ConnectError:
        return OFF
    except httpx.HTTPError as e:
        return f"Web search failed: {e}"
    return numbered(results) if results else f"No web results for {query!r}."


@mcp.tool()
async def fetch_page(url: str, max_chars: int = 6000) -> str:
    """Read one web page (http or https link) and return its main text."""
    try:
        text = await fetch(url, max(500, min(max_chars, 20000)))
    except Blocked as e:
        return f"Can't read that page: {e}."
    except httpx.HTTPError as e:
        return f"Couldn't fetch {url}: {e}"
    return text or f"{url} has no readable text."


@mcp.tool()
async def research(question: str, pages: int = 3) -> str:
    """Research a question on the web: search, read the top pages, return excerpts with numbered links.

    Use for current events, prices, releases, facts that change, or anything the user asks to
    look up online. Answer from the excerpts and cite them as [1], [2] with their links.
    """
    try:
        results = await search(question, 6)
    except httpx.ConnectError:
        return OFF
    except httpx.HTTPError as e:
        return f"Web search failed: {e}"
    if not results:
        return f"No web results for {question!r}."
    picked = results[: max(1, min(pages, 5))]

    async def excerpt(r):
        try:
            return await fetch(r["url"], EXCERPT_CHARS)
        except (Blocked, httpx.HTTPError):
            return ""

    texts = await asyncio.gather(*(excerpt(r) for r in picked))
    return "\n\n".join(
        f"[{i}] {r['title']}\n{r['url']}\n{text or r['snippet']}" for i, (r, text) in enumerate(zip(picked, texts), 1)
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

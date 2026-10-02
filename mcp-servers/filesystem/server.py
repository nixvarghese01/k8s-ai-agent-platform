"""Read-only filesystem MCP server.

Exposes one folder (FILES_ROOT, mounted read-only in k3s) to the agent through three tools:
list_dir, read_file and search_files. Every path is resolved and must stay inside the root,
so `..` and symlinks can't reach the rest of the disk. Served over MCP streamable HTTP at
http://<host>:8000/mcp.
"""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

ROOT = Path(os.environ.get("FILES_ROOT", "/data")).resolve()
MAX_READ_CHARS = int(os.environ.get("MAX_READ_CHARS", "20000"))
MAX_SEARCH_FILE_BYTES = 1_000_000  # content search skips bigger files

mcp = FastMCP(
    "filesystem",
    instructions="Read-only access to the user's files. Paths are relative to the shared folder.",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,  # no session state, so the pod can restart without breaking clients
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok" if ROOT.is_dir() else "root missing", 200 if ROOT.is_dir() else 503)


def resolve(path: str) -> Path:
    """Map a user-supplied path to an absolute path inside ROOT, or raise ValueError."""
    p = (ROOT / path.lstrip("/\\")).resolve()
    if p != ROOT and not p.is_relative_to(ROOT):
        raise ValueError(f"path is outside the shared folder: {path}")
    return p


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix() or "."


MAX_LIST_ENTRIES = 200


@mcp.tool()
def list_dir(path: str = ".", depth: int = 2) -> str:
    """List files and folders under a folder of the shared folder ("." is the top).

    Goes `depth` levels down (default 2), so one call usually shows everything.
    Returns one entry per line: "dir  <path>/" or "file <path> (<size> bytes)".
    """
    d = resolve(path)
    if not d.is_dir():
        raise ValueError(f"not a folder: {path}")
    lines: list[str] = []

    def walk(folder: Path, level: int):
        for entry in sorted(folder.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if len(lines) >= MAX_LIST_ENTRIES:
                return
            if not entry.resolve().is_relative_to(ROOT):
                continue  # symlink pointing out of the shared folder
            if entry.is_dir():
                lines.append(f"dir  {rel(entry)}/")
                if level < depth:
                    walk(entry, level + 1)
            else:
                lines.append(f"file {rel(entry)} ({entry.stat().st_size} bytes)")

    walk(d, 1)
    if len(lines) >= MAX_LIST_ENTRIES:
        lines.append(f"[... stopped at {MAX_LIST_ENTRIES} entries; list a subfolder]")
    return "\n".join(lines) or "(empty folder)"


@mcp.tool()
def read_file(path: str) -> str:
    """Read a text file from the shared folder. Long files are cut off at MAX_READ_CHARS."""
    f = resolve(path)
    note = ""
    if not f.is_file():
        # Small models often drop the extension or get the case wrong: "readme" -> README.md
        name = Path(path).name.lower()
        matches = [
            c
            for c in sorted(ROOT.rglob("*"))
            if c.is_file() and c.resolve().is_relative_to(ROOT) and name in (c.name.lower(), c.stem.lower())
        ]
        if len(matches) != 1:
            hint = f" Did you mean: {', '.join(rel(c) for c in matches[:5])}?" if matches else ""
            raise ValueError(f"not a file: {path}.{hint} Use list_dir to see the exact paths.")
        f = matches[0]
        note = f"[{path} not found; read {rel(f)} instead]\n"
    text = f.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + f"\n\n[... cut off, file has {len(text)} characters]"
    return note + text


@mcp.tool()
def search_files(query: str, path: str = ".", max_results: int = 20) -> str:
    """Find files under a folder whose name or text contains `query` (case-insensitive).

    Returns one match per line: "<file>: name" or "<file>:<line number>: <line>".
    """
    base = resolve(path)
    q = query.lower()
    results: list[str] = []
    for f in sorted(base.rglob("*")):
        if len(results) >= max_results:
            break
        if not f.is_file() or not f.resolve().is_relative_to(ROOT):
            continue
        if q in f.name.lower():
            results.append(f"{rel(f)}: name")
            continue
        if f.stat().st_size > MAX_SEARCH_FILE_BYTES:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        for n, line in enumerate(text.splitlines(), 1):
            if q in line.lower():
                results.append(f"{rel(f)}:{n}: {line.strip()[:200]}")
                break  # one hit per file keeps the answer short for a 3B model
    return "\n".join(results) or "no matches"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

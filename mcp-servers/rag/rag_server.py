"""RAG MCP server: one tool, search_documents, over the Qdrant collection rag_index.py fills.

Returns the passages closest in meaning to the question, each with its source "file:lines", so
the agent can answer from them and cite them. Served over MCP streamable HTTP at
http://<host>:8000/mcp, like the filesystem server.
"""

import os

from llama_index.core import VectorStoreIndex
from mcp.server.fastmcp import FastMCP
from qdrant_client import QdrantClient
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from rag_store import COLLECTION, QDRANT_URL, LiteLLMEmbedding, vector_store

TOP_K = int(os.environ.get("TOP_K", "4"))
# nomic-embed-text cosine scores (2026-10-03): the right passage scores 0.66-0.77, off-topic
# questions top out at ~0.53. Keep passages above MIN_SCORE and close to the best one, so a
# 3B model isn't handed loosely related text to pad its answer with.
MIN_SCORE = float(os.environ.get("MIN_SCORE", "0.6"))
SCORE_MARGIN = float(os.environ.get("SCORE_MARGIN", "0.05"))
MAX_PASSAGE_CHARS = 1200  # keeps 4 passages well inside chat-tools' context

mcp = FastMCP(
    "rag",
    instructions="Search the user's indexed documents by meaning. Every passage comes with its source.",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
)

client = QdrantClient(url=QDRANT_URL)
_retrievers = {}


def retriever(top_k: int):
    if top_k not in _retrievers:
        index = VectorStoreIndex.from_vector_store(vector_store(client), embed_model=LiteLLMEmbedding())
        _retrievers[top_k] = index.as_retriever(similarity_top_k=top_k)
    return _retrievers[top_k]


def relevant(results, min_score: float = MIN_SCORE, margin: float = SCORE_MARGIN):
    """Results scoring at least min_score and within margin of the best one."""
    if not results:
        return []
    cut = max(min_score, max(r.score or 0 for r in results) - margin)
    return [r for r in results if (r.score or 0) >= cut]


def format_results(results) -> str:
    """Numbered passages: "[1] notes/a.md:3-9 (score 0.71)" then the text."""
    if not results:
        return "No matching passages. Try other words, or list_dir / read_file."
    out = []
    for i, r in enumerate(results, 1):
        meta = r.node.metadata
        text = r.node.get_content().strip()
        if len(text) > MAX_PASSAGE_CHARS:
            text = text[:MAX_PASSAGE_CHARS] + " [...]"
        out.append(f"[{i}] {meta.get('file_path', '?')}:{meta.get('lines', '?')} (score {r.score or 0:.2f})\n{text}")
    return "\n\n".join(out)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    try:
        client.get_collections()
        return PlainTextResponse("ok")
    except Exception as e:
        return PlainTextResponse(f"qdrant unreachable: {e}", 503)


@mcp.tool()
def search_documents(query: str, top_k: int = TOP_K) -> str:
    """Search the user's documents and notes by meaning and return the most relevant passages.

    Use it for any question about what the documents say. Each passage starts with its source
    as "[n] <file>:<lines>"; cite those sources in the answer.
    """
    if not client.collection_exists(COLLECTION):
        return "No documents are indexed yet (the rag-index job has not run). Use list_dir / read_file."
    return format_results(relevant(retriever(max(1, min(top_k, 10))).retrieve(query)))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

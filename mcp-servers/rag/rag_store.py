"""Shared by the indexer (rag_index.py) and the search server (rag_server.py).

Embeddings come from LiteLLM's `embed-default` alias (nomic-embed-text on Ollama), never from
Ollama directly, and vectors live in one Qdrant collection. Each chunk keeps its file and line
range, so answers can cite "notes/meeting.md:3-9".
"""

import os

import httpx
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from pydantic import Field
from qdrant_client import QdrantClient

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://litellm.llm.svc.cluster.local:4000/v1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "embed-default")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant.storage.svc.cluster.local:6333")
COLLECTION = os.environ.get("COLLECTION", "docs")


class LiteLLMEmbedding(BaseEmbedding):
    """OpenAI-style /embeddings through LiteLLM, with nomic-embed-text's task prefixes.

    nomic-embed-text is trained with "search_query: " / "search_document: " in front of the text;
    leaving them out costs retrieval quality. Changing the model or prefixes means re-indexing.
    """

    base_url: str = Field(default=LLM_BASE_URL)
    query_prefix: str = Field(default="search_query: ")
    document_prefix: str = Field(default="search_document: ")
    timeout: float = Field(default=300.0)  # CPU embedding of a batch can be slow

    def __init__(self, **kwargs):
        kwargs.setdefault("model_name", EMBED_MODEL)
        super().__init__(**kwargs)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model_name, "input": texts},
            headers={"Authorization": "Bearer sk-local"},  # LiteLLM has no key; clients need a value
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed([self.query_prefix + query])[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed([self.document_prefix + text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self.document_prefix + t for t in texts])

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)


def vector_store(client: QdrantClient | None = None) -> QdrantVectorStore:
    return QdrantVectorStore(client=client or QdrantClient(url=QDRANT_URL), collection_name=COLLECTION)

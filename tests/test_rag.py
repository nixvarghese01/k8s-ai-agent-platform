"""RAG indexer and search: in-memory Qdrant and a word-hashing fake embedding, no cluster or LLM."""

import hashlib
import math
import re

import pytest
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.node_parser import SentenceSplitter
from qdrant_client import QdrantClient

import rag_index
import rag_server
from rag_store import COLLECTION, LiteLLMEmbedding

DIM = 64


class WordEmbedding(BaseEmbedding):
    """Bag of words hashed into DIM buckets: texts sharing words get close vectors."""

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for w in re.findall(r"[a-z]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def _get_query_embedding(self, query):
        return self._vec(query)

    def _get_text_embedding(self, text):
        return self._vec(text)

    async def _aget_query_embedding(self, query):
        return self._vec(query)


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "meeting.md").write_text(
        "# Meeting\n\nWe decided to buy a cooling stand.\nBudget is fifty euros.\n", encoding="utf-8"
    )
    (tmp_path / "recipes.txt").write_text("Pancakes need flour, milk and eggs.\n", encoding="utf-8")
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04\x00\xff")  # skipped: unsupported format
    return tmp_path, QdrantClient(":memory:"), WordEmbedding()


def search(client, embed, query, k=2):
    from llama_index.core import VectorStoreIndex

    index = VectorStoreIndex.from_vector_store(rag_index.vector_store(client), embed_model=embed)
    return index.as_retriever(similarity_top_k=k).retrieve(query)


def test_index_then_search_cites_file_and_lines(setup):
    root, client, embed = setup
    stats = rag_index.run(root, client, embed)
    assert stats["files"] == 2 and stats["indexed"] == 2 and stats["removed"] == 0

    top = search(client, embed, "cooling stand budget")[0]
    assert top.node.metadata["file_path"] == "notes/meeting.md"
    assert top.node.metadata["lines"] == "1-4"
    assert "cooling stand" in top.node.get_content()


def test_second_run_skips_unchanged_and_follows_edits_and_deletes(setup):
    root, client, embed = setup
    rag_index.run(root, client, embed)
    assert rag_index.run(root, client, embed) == {"files": 2, "indexed": 0, "chunks": 0, "removed": 0, "unchanged": 2}

    (root / "recipes.txt").write_text("Waffles need butter.\n", encoding="utf-8")
    (root / "notes" / "meeting.md").unlink()
    stats = rag_index.run(root, client, embed)
    assert stats["indexed"] == 1 and stats["removed"] == 1
    assert rag_index.indexed(client).keys() == {"recipes.txt"}
    assert "Waffles" in search(client, embed, "waffles butter", k=1)[0].node.get_content()


def test_plan():
    to_index, to_delete = rag_index.plan({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "old", "d": "4"})
    assert to_index == ["b", "c"]
    assert to_delete == ["b", "d"]  # changed files are deleted first, then re-indexed


def test_chunks_carry_line_ranges():
    text = "\n".join(f"Line {i} says something about topic {i}." for i in range(1, 61))
    nodes = rag_index.chunks("long.md", text, "h", SentenceSplitter(chunk_size=64, chunk_overlap=0))
    assert len(nodes) > 2
    assert nodes[0].metadata["lines"].startswith("1-")
    first, last = (int(x) for x in nodes[-1].metadata["lines"].split("-"))
    assert last == 60 and first > 1
    assert "file_hash" in nodes[0].excluded_embed_metadata_keys


def test_format_results(setup):
    root, client, embed = setup
    rag_index.run(root, client, embed)
    out = rag_server.format_results(search(client, embed, "pancakes flour", k=1))
    assert re.match(r"\[1\] recipes\.txt:1-1 \(score \d\.\d\d\)\n.*Pancakes", out)
    assert "No matching passages" in rag_server.format_results([])


def test_embedding_adds_nomic_prefixes(monkeypatch):
    sent = []
    emb = LiteLLMEmbedding()
    monkeypatch.setattr(LiteLLMEmbedding, "_embed", lambda self, texts: sent.extend(texts) or [[0.0]] * len(texts))
    emb.get_query_embedding("where is the budget?")
    emb.get_text_embedding_batch(["doc one", "doc two"])
    assert sent == ["search_query: where is the budget?", "search_document: doc one", "search_document: doc two"]
    assert emb.model_name == "embed-default" and COLLECTION == "docs"


def test_relevant_keeps_passages_near_the_best():
    class R:
        def __init__(self, score):
            self.score = score

    scores = lambda rs: [r.score for r in rs]
    assert scores(rag_server.relevant([R(0.66), R(0.54), R(0.53)])) == [0.66]  # one clear hit
    assert scores(rag_server.relevant([R(0.77), R(0.77), R(0.74), R(0.72)])) == [0.77, 0.77, 0.74, 0.72]
    assert rag_server.relevant([R(0.53), R(0.52)]) == []  # off-topic question: no context

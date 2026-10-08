# Week 3: document Q&A (RAG, LlamaIndex + Qdrant)

**Deliverable:** answers from your documents, with sources. ✅ (#7)

## What runs
- `rag-index` CronJob (every 15 min): LlamaIndex splits text files into 256-token chunks that keep
  their `file:lines`, embeds them with `embed-default` through LiteLLM, stores them in Qdrant
  collection `docs`. Only new or changed files are re-embedded (sha256 per file).
- `mcp-rag`: MCP tool `search_documents`.
- The agent retrieves **before** calling the model and answers from the passages in one call,
  with a "Sources: file:lines" line.

## Decisions
- **Retrieve first, answer without tools:** with the search as a tool, `qwen2.5:3b` skipped it on
  3 of 4 questions, searched twice, and returned empty replies with tools bound. Retrieve-first:
  every test question right, one model call.
- **Score cut-off 0.60, margin 0.05:** right passages scored 0.66–0.77, off-topic at most 0.53;
  loosely related passages made the model pad its answer.
- **"Which files…" questions skip retrieval** (a regex): otherwise the model described the README
  instead of listing the folder.
- nomic-embed-text's `search_query:` / `search_document:` prefixes are added.

## Measured
- Document questions 3–11 s (median ~7 s), down from 12–42 s with search as a tool. Target 3–5 s:
  partly met. Index: 65 chunks from 4 files; a run with nothing new takes seconds.

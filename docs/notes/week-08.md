# Week 8: voice, OCR, docs, demo

**Deliverable:** the full platform. ✅ (#12), with workflows 5 and 6 still open (see below)

## What runs
- **Voice** (profile `voice`, ~0.7 GB): an own OpenAI-compatible server, faster-whisper `base`
  (int8) for speech-to-text and Piper `en_US-amy-medium` for text-to-speech; Open WebUI's
  microphone, read-aloud and call buttons use it.
- **OCR**: the document index reads PDFs (text layer, Tesseract for scanned pages), images and
  Word files; PDF passages are cited by page.
- **Docs**: README §9 now shows target vs measured for every workflow, honestly; weekly notes;
  [DEMO.md](../DEMO.md) is a 15-shot recording script.

## Decisions
- Own voice server instead of *speaches* (no stable release since 2025): ~150 lines, two
  maintained libraries, built and deployed by the same CI/ArgoCD path as the other images.
- Tesseract over PaddleOCR: light; enough for printed scans and photos of notices.
- Voice through Open WebUI rather than a new UI: no new hostname, it already has mic/call UI.

## Fixed on the way
- faster-whisper 1.2.1 broke with PyAV 19 (`metadata_errors` removed): pinned PyAV 18.1.0 after
  testing 14.4 (fails), 15.1–18.1 (work), 19.0 (fails).

## Measured
- Voice, warm in k3s (2 CPUs): speech-to-text 3.3–3.6 s, text-to-speech 0.6 s; spoken question →
  spoken document answer ~11 s (target 3–6 s: partly met).
- OCR: a PNG notice and an image-only PDF receipt indexed in ~5 s each; "how much rent did I pay
  for October" → "5,000 AED on 3 October 2026", `Sources: docs/scans/rent-receipt.pdf p.1`.
- CI ran the real Tesseract test; build, bump and ArgoCD deployed `voice` and `mcp-rag` with no
  manual step. 47 tests.

## Not built (follow-up)
- Workflow 5 (calendar) and 6 (web research): need time/calendar, web-search and fetch MCP
  servers, and calendar credentials. Workflow 1's memory needs a memory MCP; workflow 7 has tool
  chaining but no planning step.

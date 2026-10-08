# Changelog

Notable changes, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions: [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-08

First release: the full platform from the 8-week build plus hardening. All 10 use cases work;
`make e2e` passes; the golden evaluation set scores 100% on `qwen2.5:3b`.

### Added
- **Platform:** k3s in WSL2, Traefik with HTTPS (local CA), on-demand profiles (mlops,
  observability, automation, voice, gitops, research), Headlamp cluster UI.
- **LLM stack:** Ollama (CPU-only, 3B models), LiteLLM gateway with aliases, Open WebUI.
- **Agent:** LangGraph agent with retrieval-first answering, memory, web research and multi-step
  requests; six MCP servers (filesystem, rag, triage, memory, calendar, web); SearXNG.
- **RAG:** LlamaIndex indexer over notes, PDFs, scans (Tesseract OCR) and Word files into Qdrant,
  answers with sources.
- **MLOps:** message-triage model trained nightly (Dagster + Optuna), MLflow registry with
  champion/challenger, BentoML serving, Evidently drift report; SeaweedFS (S3) and Postgres.
- **Automation:** n8n e-mail triage and daily briefing (calendar, to-dos, headlines).
- **Voice:** faster-whisper speech-to-text and Piper text-to-speech for Open WebUI.
- **Observability:** Arize Phoenix (OpenTelemetry traces), Prometheus, Grafana dashboard.
- **Security:** Authelia single sign-on for every UI with no second login (OIDC for Argo CD),
  network policies against forged sign-in headers.
- **Model management:** Models page with a model per use case, RAM/CPU fit check and expected
  speed; golden-set evaluation and quality gate; audit trail and rollback.
- **Delivery:** GitHub Actions (tests, linters, image builds to GHCR pinned by digest), Argo CD
  GitOps, `make e2e` end-to-end check.
- **Repository:** branching model (feature/bugfix/hotfix/docs branches into `development`,
  releases `development` → `main`, hotfixes into `main`), branch and tag protection rulesets,
  `branch policy` check, `CODEOWNERS`, automated releases from `CHANGELOG.md` with images
  promoted by digest, image builds on hotfix branches, Dependabot, cleanup that keeps released
  images.
- **Docs:** README, weekly notes, demo script, `SECURITY.md`, `CONTRIBUTING.md`.

### Known limitations
- CPU-only answers take seconds (3–40 s per question); see README 9.
- The spam classifier is trained on SMS spam and misses phishing e-mails (#31).
- Model digests aren't pinned yet (#32).

[Unreleased]: https://github.com/nixvarghese01/k8s-ai-agent-platform/compare/v1.0.0...development
[1.0.0]: https://github.com/nixvarghese01/k8s-ai-agent-platform/releases/tag/v1.0.0

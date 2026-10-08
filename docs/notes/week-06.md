# Week 6: automation and observability (n8n, Phoenix, Prometheus, Grafana)

**Deliverable:** automation + traces. ✅ (#10)

## What runs
- Profile `observability` (~0.8 GB): **Phoenix** (https://phoenix.ai.local) receives a trace per
  agent run (LangGraph → retrieve → search → answer → model call) and per LLM call through
  LiteLLM; **Prometheus** (three scrape jobs: Traefik, container CPU/memory, annotated pods such
  as BentoML); **Grafana** (https://grafana.ai.local) with a provisioned *Platform overview*
  dashboard, signed in through the platform login.
- Profile `automation` (~0.4 GB): **n8n** (https://n8n.ai.local) with two workflows imported and
  activated from Git on every start: *Email triage* (webhook → classifier → spam verdict, or LLM
  category + summary) and *Daily briefing* (07:30 → agent → `E:\ai-files\briefings\<date>.md`).

## Decisions
- **Phoenix instead of Langfuse v3:** one container + SQLite (~0.5 GB) versus web + worker +
  ClickHouse + Redis (~1.5–2 GB); OpenTelemetry-native.
- **Small Prometheus** instead of kube-prometheus-stack (~1 GB): only the series the dashboard
  uses, 7 days; 36 MB.
- **Grafana trusts Authelia's `Remote-User` header**: no second password.
- **n8n on SQLite**, so `automation` doesn't need the `mlops` profile's Postgres. Workflows live
  in a ConfigMap (Git is the truth); UI edits are replaced on restart.
- Briefings go into the shared folder, so the document search indexes them too.

## Fixed on the way
- FastAPI emits spans to any *global* tracer, so health probes buried the agent's traces: the
  agent keeps Phoenix's tracer private to the LangChain instrumentation.
- n8n reads Kubernetes' injected `N8N_PORT=tcp://…` (same trap as Authelia): service links off.
- n8n 2.x activates on import only in queue mode: import, then `n8n publish:workflow`.
- **Every `*.ai.local` page failed in Chrome on a network without IPv6** (NXDOMAIN): WSL relays
  Traefik to Windows' `[::1]` only, and Chrome skips IPv6-only names then. Fixed with hosts
  entries on `127.0.0.1` plus Windows port proxies `127.0.0.1:80/443 → [::1]`.

## Measured
- Email triage: spam 1.2 s, normal mail 15 s with category, summary and needs-reply (target
  30–60 s). Daily briefing: 29 s, file written.
- All profiles on: 6.9 GB used in WSL, 11.1 GB available. Phoenix ~0.5 GB, Grafana ~0.28 GB,
  Prometheus 36 MB, n8n ~0.38 GB.

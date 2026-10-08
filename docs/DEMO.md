# Demo: recording script (~10 minutes)

A shot list for recording the platform end to end, in an order where each part builds on the
last. Every step was run on the reference laptop (CPU only); the times are what to expect.

## Before you record

1. Start everything: `.\local-up -Profile mlops,observability,automation,gitops,voice,research`
   (about 2 minutes; `.\infra\scripts\platform.ps1 status` should be all green).
2. Sign in once at https://auth.ai.local with your own login (`.\infra\scripts\platform.ps1 set-login`).
3. Warm the models so the recording isn't waiting on first loads: ask the agent one question at
   https://agent.ai.local and click the speaker button once in https://chat.ai.local.
4. Have these files in `E:\ai-files`: the notes, `docs\scans\gym-membership.png`,
   `docs\scans\rent-receipt.pdf` (both image-only, so only OCR can read them).
5. Record the screen at 1080p; close other heavy apps (the laptop has 18 GB for WSL).

## Shot list

| # | Show | Do / say | Expect |
|---|---|---|---|
| 1 | GitHub repo, README top | "One laptop, no cloud, no GPU: k3s, local 3B models, MCP tools, MLOps and GitOps." | — |
| 2 | Headlamp (https://headlamp.ai.local) → Workloads | The namespaces: llm, agent, ui, storage, mlops, observability, automation, voice, auth, argocd | all Running |
| 3 | Terminal: `.\infra\scripts\platform.ps1 profile` | "Only the core runs by default; the rest is switched on by profile." | list of on/off |
| 4 | https://agent.ai.local | Ask **"What was decided in the meeting on 2026-10-01?"**, expand the 🔧 line | 3 decisions + `Sources: notes/meeting-2026-10-01.md:1-6`, ~7 s |
| 5 | same | Ask **"How much rent did I pay for October, and when?"** | 5,000 AED on 3 October, `Sources: docs/scans/rent-receipt.pdf p.1` (OCR), ~7 s |
| 6 | same | Ask **"Is this message spam? 'URGENT: your account is locked, reply with your PIN'"** | `classify_message` → SPAM with confidence, ~11 s |
| 6a | same | **"Remember that my manager is Maria Lopez"**, then **New chat** and **"Who is my manager?"** | stored at once; answered in a new conversation in ~3 s |
| 6b | same | **"Add a dentist appointment on Monday at 10am"**, then **"What's on my calendar next week?"** | `add_event`, then `list_events` shows it, ~10–16 s each |
| 6c | same (profile `research` on) | **"Search the web for the latest Kubernetes release"** | answer citing [1] with the link, ~18 s |
| 6d | same | **"List the files in my shared folder and then tell me what my to-do list says"** | `plan` → `list_dir` → `read_file`; slow on CPU (~1–1.5 min) |
| 7 | https://chat.ai.local | Click the microphone, say **"When is my gym membership renewal due?"**, send; click the speaker on the answer | transcribed in ~3 s; answer read aloud |
| 8 | https://phoenix.ai.local → project `agent` | Open the trace of question 4: LangGraph → retrieve → search_documents → answer → model call | every step with timings |
| 9 | https://grafana.ai.local | *Platform overview*: memory and CPU by namespace, requests per UI | live panels |
| 10 | https://mlflow.ai.local → Models → `message-triage` | "Trained nightly by Dagster with Optuna; `champion` moves only when F1 improves." | v1/v2, test F1 0.976 |
| 11 | https://dagster.ai.local → `triage_model`, `triage_drift_report` | "Drift report compares live traffic with the training data." | check passed / warning |
| 12 | https://n8n.ai.local → *Email triage* | Run it from a terminal: `kubectl -n ui exec deploy/agent-ui -- python -c "import httpx; print(httpx.post('http://n8n.automation.svc.cluster.local:5678/webhook/email-triage', json={'from':'maria@company.com','subject':'Review moved','body':'The review moves to Thursday 3pm, can you update the slides?'}, timeout=300).json())"` | `ham`, `work`, a one-line summary, `needs_reply: true` |
| 13 | GitHub → Actions | The last `ci` and `build` runs, then the bot's "Deploy images built from …" commit | green |
| 14 | https://argocd.ai.local → `platform` | "ArgoCD deployed that commit by itself." | Synced, Healthy |
| 15 | README §9 | Close on the measured workflow table, including what isn't built yet | — |

## Honest notes for the voice-over
- Everything is CPU-only: answers take seconds, not milliseconds; the README states the targets
  and the measured times side by side.
- The calendar reads `.ics` files and feeds; it doesn't write back to Google/Outlook. Web
  research is the one feature that leaves the laptop (search queries), so it has its own profile.
- One login for everything: Open WebUI, n8n and Grafana take the user from Authelia's headers, ArgoCD
  signs in over OpenID Connect, Headlamp gets its token from Traefik (README §6.14).

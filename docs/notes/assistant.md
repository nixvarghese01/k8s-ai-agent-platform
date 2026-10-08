# After week 8: memory, calendar, web research, planning (#27)

**Deliverable:** the last four workflows (1, 5, 6, 7) and a fuller daily briefing (10). ✅
All ten README workflows now run.

## What runs
- **mcp-memory** (core, 54 MB): `remember` / `recall` / `forget`, facts in SQLite on a volume.
  "Remember that ..." is stored without a model call; relevant facts reach every question.
- **mcp-calendar** (core, 57 MB): `now` / `list_events` / `add_event` over `.ics` files in
  `E:\ai-files\calendar` and optional read-only feed URLs (Secret `agent/calendar-feeds`).
- **mcp-web** (core, 98 MB) + **SearXNG** (profile `research`, 129 MB): `web_search`,
  `fetch_page`, and `research` (search + read 3 pages in one call). Public addresses only.
- **Agent:** routes "remember/forget" and web questions to fixed steps, splits multi-step
  requests into their parts, gives the model today's date, keeps conversations in SQLite (survive restarts),
  and loads MCP servers that were down at start once they come up.
- **Daily briefing:** calendar + to-dos + headlines.

## Decisions
- `.ics` files and feed URLs instead of Google/Microsoft OAuth: works offline, no credentials,
  any calendar app can export or publish one. Adding events writes the local `agent.ics`.
- SearXNG instead of a search API: no key, no account, self-hosted; its own profile, because it
  is the one feature that sends data (queries) off the laptop.
- Memory by shared words, not embeddings: a few hundred personal facts, answered in
  milliseconds, nothing to re-index.
- Rules before the model where a rule is enough (remember, research, calendar routing): a 3B
  model skipped or repeated tool calls when it had to decide these itself.

## Fixed on the way
- The golden set (#29) found the model-made plan harmful: the 3B model listed tools at random and,
  pushed to finish the plan, once added a calendar event. Multi-step requests are now split at
  "and then" and each part is asked on its own: 3/3 correct, 34–39 s, nothing invented.
- A saved fact went to the tool loop, which called `list_dir` and credited a random file: facts
  now go to the one-call answer step (15 s → 3 s, correct).

## Measured (qwen2.5:3b, CPU)
- Remember 0.2 s; recall in a new conversation 3.2 s; add event 10 s; list a week 12–16 s;
  web research 17–19 s; two-part request 34–39 s (was 57–117 s with a model-made plan); briefing 29 s.
- `make e2e` covers all four; 38 unit tests for the agent and the three servers.

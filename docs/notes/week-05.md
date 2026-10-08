# Week 5: model serving as an agent tool (BentoML + Evidently)

**Deliverable:** the trained model used by the agent, and watched for drift. ✅ (#9)

## What runs
- BentoML service `triage` (profile `mlops`, ~300 MB): loads `models:/message-triage@champion`
  from MLflow, re-checks the alias every 5 minutes (a nightly promotion is picked up without a
  restart), logs every request to `s3://triage/requests/`. Swagger UI: https://triage.ai.local.
- MCP server `mcp-triage` (core, ~40 MB): tool `classify_message`; when `mlops` is off it tells
  the agent how to start it instead of failing.
- Dagster asset `triage_drift_report` (daily 03:00, job `triage_monitoring`): Evidently compares
  the last 7 days of requests with the test set on text descriptors and the model's outputs;
  HTML report in MLflow (`message-triage-monitoring`), warning check at drift share > 0.5.

## Decisions
- The model server is in `mlops` (it needs MLflow); the tool is in the core and degrades clearly.
- Spam/scam/phishing/classify questions skip document retrieval (`TOOL_INTENT`), so a README
  passage that mentions spam can't answer them.
- Drift on descriptors, not raw text: length, digits, capitals, `!`, links, money signs, plus
  spam probability and label. Reference = test set scored by the current champion.
- A test caught a real bug before deploy: `self.model` (the pipeline) shadowed the `model` API.

## Measured
- `/classify` ~1.3 s; agent spam question 11 s warm (34 s cold). Both test messages right.
- Like-training traffic (84): drift share 0.33, check passed. With 60 modern phishing messages
  (144): drift share 0.89, spam rate 13% → 40%, check warned. The model caught only 47/60 (78%)
  of the modern phishing: the signal to retrain with newer data.

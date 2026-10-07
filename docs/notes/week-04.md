# Week 4: training pipeline (MLflow + Dagster + Optuna)

**Deliverable:** a model trained, tracked and registered on a schedule. ✅ (#8)

## What runs (profile `mlops`)
- Postgres 18 (metadata for MLflow and Dagster), SeaweedFS (S3: buckets `mlflow`, `dagster`,
  `triage`), MLflow 3 (https://mlflow.ai.local), Dagster webserver + daemon
  (https://dagster.ai.local).
- Assets `sms_spam_raw → sms_spam_split → triage_model`: SMS Spam Collection (pinned sha256),
  stratified 80/20 split, Optuna (30 trials × 5-fold CV) over TF-IDF + logistic regression,
  every trial an MLflow child run, model registered as `message-triage`.
- Schedule `triage_nightly` 02:00 Asia/Dubai, one run at a time, max 2 CPUs; `make train` now.

## Decisions
- **SeaweedFS instead of MinIO:** MinIO went source-only in late 2025 (no maintained images);
  SeaweedFS is Apache-2.0 and what Kubeflow Pipelines switched to.
- **Alias `champion` moves only on a better test F1**, compared at the 4 decimals stored (a
  same-score re-run once promoted itself on float noise; fixed).
- MLflow's GenAI job runner is off (8 × 240 MB, OOM at 1 GiB); Dagster talks to Postgres through
  psycopg2, MLflow through psycopg 3.

## Measured
- 13.5 min per run on CPU. Test set (1,115 messages): F1 0.976, precision 1.0, recall 0.953,
  accuracy 99.4%, ROC AUC 0.998. Idle RAM ≈ 1.6 GB for the four services; 1.3 GB while training.

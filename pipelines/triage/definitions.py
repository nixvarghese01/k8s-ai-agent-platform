"""Dagster definitions: the message-triage assets, a job over them and a nightly schedule.

    sms_spam_raw ─► sms_spam_split ─► triage_model (+ check: test F1 >= 0.90)
                          └──────────► triage_drift_report (+ check: drift share <= 0.5)
                                       (served requests vs test set, Evidently; daily 03:00)

Training runs at night (02:00, SCHEDULE_TIMEZONE) because that's when the laptop is coolest
(README §12). If the platform is down then, the run is simply skipped; run it by hand from
https://dagster.ai.local (Materialize all) or `make train`.
"""

import os
from datetime import datetime, timezone

import dagster as dg
import numpy as np
import pandas as pd

from triage import data, drift, train

TIMEZONE = os.environ.get("SCHEDULE_TIMEZONE", "Asia/Dubai")
MLFLOW_UI = os.environ.get("MLFLOW_UI_URL", "https://mlflow.ai.local")
MIN_TEST_F1 = 0.90
MAX_DRIFT_SHARE = 0.5  # more than half the descriptors drifted: look at the report
TRIAGE_BUCKET = os.environ.get("TRIAGE_BUCKET", "triage")  # where the BentoML service logs requests


@dg.asset(group_name="triage", kinds={"pandas"})
def sms_spam_raw(context: dg.AssetExecutionContext) -> pd.DataFrame:
    """SMS Spam Collection from UCI, checked against its pinned sha256."""
    df = data.parse(data.download())
    context.add_output_metadata({"rows": len(df), "spam": int((df["label"] == "spam").sum()), "sha256": data.SHA256})
    return df


@dg.asset(group_name="triage", kinds={"pandas"})
def sms_spam_split(context: dg.AssetExecutionContext, sms_spam_raw: pd.DataFrame) -> dict:
    """Stratified 80/20 train/test split with a fixed seed."""
    tr, te = data.split(sms_spam_raw)
    context.add_output_metadata({"train_rows": len(tr), "test_rows": len(te)})
    return {"train": tr, "test": te}


class TrainConfig(dg.Config):
    n_trials: int = 30  # Optuna trials; each is a 5-fold cross-validation (~1-3 s on CPU)
    timeout_s: int = 1800  # stop tuning after this many seconds, whatever n_trials says


@dg.asset(
    group_name="triage",
    kinds={"sklearn", "mlflow"},
    check_specs=[dg.AssetCheckSpec("test_f1_at_least_0_90", asset="triage_model")],
)
def triage_model(context: dg.AssetExecutionContext, config: TrainConfig, sms_spam_split: dict) -> dg.MaterializeResult:
    """Optuna-tuned TF-IDF + logistic regression, logged and registered in MLflow as
    message-triage; alias "champion" moves when the test F1 improves."""
    r = train.train_and_register(sms_spam_split["train"], sms_spam_split["test"],
                                 n_trials=config.n_trials, timeout=config.timeout_s)
    m = r["metrics"]
    context.log.info("version %s, test F1 %.4f, champion: %s", r["version"], m["f1"], r["champion"])
    return dg.MaterializeResult(
        metadata={
            "mlflow_run": dg.MetadataValue.url(f"{MLFLOW_UI}/#/experiments/{r['experiment_id']}/runs/{r['run_id']}"),
            "model_version": r["version"],
            "champion": r["champion"],
            "trials": r["trials"],
            "cv_f1": round(r["cv_f1"], 4),
            **{f"test_{k}": round(v, 4) for k, v in m.items()},
            "best_params": dg.MetadataValue.json(r["best_params"]),
        },
        check_results=[dg.AssetCheckResult(check_name="test_f1_at_least_0_90", passed=m["f1"] >= MIN_TEST_F1,
                                           metadata={"test_f1": round(m["f1"], 4)})],
    )


class DriftConfig(dg.Config):
    window_days: int = drift.WINDOW_DAYS  # how many days of logged requests count as "current"


@dg.asset(
    group_name="triage_monitoring",
    kinds={"evidently", "mlflow"},
    check_specs=[dg.AssetCheckSpec("drift_share_at_most_0_5", asset="triage_drift_report")],
)
def triage_drift_report(context: dg.AssetExecutionContext, config: DriftConfig,
                        sms_spam_split: dict) -> dg.MaterializeResult:
    """Evidently data-drift report: the messages the served model saw in the last days vs the
    held-out test set, compared on text descriptors and the model's own outputs. The HTML report
    is logged to MLflow (experiment message-triage-monitoring)."""
    import boto3
    import mlflow

    s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL"))
    requests = drift.read_requests(s3, TRIAGE_BUCKET, days=config.window_days)
    check = "drift_share_at_most_0_5"
    if len(requests) < drift.MIN_CURRENT:
        msg = f"skipped: {len(requests)} requests in {config.window_days} days, need {drift.MIN_CURRENT}"
        context.log.info(msg)
        return dg.MaterializeResult(metadata={"status": msg, "n_current": len(requests)},
                                    check_results=[dg.AssetCheckResult(check_name=check, passed=True,
                                                                       metadata={"skipped": True})])

    model = mlflow.sklearn.load_model(f"models:/{train.MODEL_NAME}@champion")
    test = sms_spam_split["test"]
    proba = model.predict_proba(test[["text"]])[:, list(model.classes_).index(train.POSITIVE)]
    reference = drift.frame(test["text"], pd.Series(np.where(proba >= 0.5, "spam", "ham")), pd.Series(proba))
    current = drift.frame(requests["text"], requests["label"], requests["spam_probability"])
    path, summary = drift.report(reference, current)

    experiment = mlflow.set_experiment("message-triage-monitoring")
    with mlflow.start_run(run_name=f"drift {datetime.now(timezone.utc):%Y-%m-%d %H:%M}") as run:
        mlflow.log_params({"window_days": config.window_days, "n_reference": len(reference), "n_current": len(current)})
        mlflow.log_metrics({"drift_share": summary["drift_share"], "drifted_columns": summary["drifted_columns"],
                            "current_spam_rate": float((current["label"] == "spam").mean())})
        mlflow.log_dict(summary["columns"], "column_drift.json")
        mlflow.log_artifact(path)
    share = summary["drift_share"]
    context.log.info("drift share %.2f (%d columns) over %d requests", share, summary["drifted_columns"], len(current))
    return dg.MaterializeResult(
        metadata={
            "drift_share": share,
            "drifted_columns": summary["drifted_columns"],
            "n_current": len(current),
            "current_spam_rate": round(float((current["label"] == "spam").mean()), 4),
            "report": dg.MetadataValue.url(f"{MLFLOW_UI}/#/experiments/{experiment.experiment_id}/runs/{run.info.run_id}/artifacts"),
            "columns": dg.MetadataValue.json(summary["columns"]),
        },
        check_results=[dg.AssetCheckResult(check_name=check, passed=share <= MAX_DRIFT_SHARE,
                                           severity=dg.AssetCheckSeverity.WARN, metadata={"drift_share": share})],
    )


triage_training = dg.define_asset_job("triage_training", selection=dg.AssetSelection.groups("triage"))
triage_monitoring = dg.define_asset_job("triage_monitoring", selection=dg.AssetSelection.assets(triage_drift_report))

triage_drift_daily = dg.ScheduleDefinition(
    name="triage_drift_daily",
    job=triage_monitoring,
    cron_schedule="0 3 * * *",  # after the 02:00 training
    execution_timezone=TIMEZONE,
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

triage_nightly = dg.ScheduleDefinition(
    name="triage_nightly",
    job=triage_training,
    cron_schedule="0 2 * * *",
    execution_timezone=TIMEZONE,
    default_status=dg.DefaultScheduleStatus.RUNNING,
)


def _resources() -> dict:
    """In k3s, assets pass data through SeaweedFS (bucket dagster), so a run can reuse the
    dataset another run stored; elsewhere (tests) the default local IO manager is used."""
    endpoint = os.environ.get("S3_ENDPOINT_URL")
    if not endpoint:
        return {}
    from dagster_aws.s3 import S3PickleIOManager, S3Resource

    return {"io_manager": S3PickleIOManager(s3_resource=S3Resource(endpoint_url=endpoint),
                                            s3_bucket=os.environ.get("DAGSTER_BUCKET", "dagster"), s3_prefix="io")}


defs = dg.Definitions(
    assets=[sms_spam_raw, sms_spam_split, triage_model, triage_drift_report],
    jobs=[triage_training, triage_monitoring],
    schedules=[triage_nightly, triage_drift_daily],
    resources=_resources(),
)

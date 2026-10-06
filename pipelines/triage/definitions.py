"""Dagster definitions: the message-triage assets, a job over them and a nightly schedule.

    sms_spam_raw ─► sms_spam_split ─► triage_model (+ check: test F1 >= 0.90)

Training runs at night (02:00, SCHEDULE_TIMEZONE) because that's when the laptop is coolest
(README §12). If the platform is down then, the run is simply skipped; run it by hand from
https://dagster.ai.local (Materialize all) or `make train`.
"""

import os

import dagster as dg
import pandas as pd

from triage import data, train

TIMEZONE = os.environ.get("SCHEDULE_TIMEZONE", "Asia/Dubai")
MLFLOW_UI = os.environ.get("MLFLOW_UI_URL", "https://mlflow.ai.local")
MIN_TEST_F1 = 0.90


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


triage_training = dg.define_asset_job("triage_training", selection=dg.AssetSelection.groups("triage"))

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
    assets=[sms_spam_raw, sms_spam_split, triage_model],
    jobs=[triage_training],
    schedules=[triage_nightly],
    resources=_resources(),
)

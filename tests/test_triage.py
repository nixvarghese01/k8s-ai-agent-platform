"""Message-triage pipeline: parsing, training + registry promotion, and the Dagster assets end to
end, with a synthetic dataset, a local SQLite MLflow and no download or cluster."""

import io
import random
import zipfile

import dagster as dg
import mlflow
import pandas as pd
import pytest
from mlflow import MlflowClient

from triage import data, definitions, train

HAM = ["see you at lunch", "call me when you get home", "the meeting moved to friday", "thanks for the notes",
       "are we still on for dinner", "running late, sorry", "can you send the file", "happy birthday mate"]
SPAM = ["win a free prize now, text WIN to 80082", "urgent! claim your cash reward, call 0900 now",
        "free entry to win tickets, reply YES", "you have won a £1000 voucher, click to claim"]


def fake_zip(n: int = 160) -> bytes:
    rnd = random.Random(0)
    lines = [f"ham\t{rnd.choice(HAM)} {i}" for i in range(n)] + [f"spam\t{rnd.choice(SPAM)} {i}" for i in range(n // 4)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SMSSpamCollection", "\n".join(lines) + "\n")
        z.writestr("readme", "test")
    return buf.getvalue()


@pytest.fixture
def tracking(tmp_path, monkeypatch):
    """A throwaway MLflow: SQLite for runs + registry, local folder for artifacts."""
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    monkeypatch.setattr(train, "EXPERIMENT", "test-triage")
    mlflow.create_experiment("test-triage", artifact_location=(tmp_path / "artifacts").as_uri())
    yield MlflowClient()
    mlflow.set_tracking_uri(None)


def test_parse_and_split_are_stratified():
    df = data.parse(fake_zip())
    assert list(df.columns) == ["label", "text"] and len(df) == 200
    tr, te = data.split(df)
    assert len(te) == 40 and (te["label"] == "spam").sum() == 8  # 20% of each class


def test_download_rejects_changed_data(monkeypatch):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(data.urllib.request, "urlopen", lambda url, timeout: Resp(b"other bytes"))
    with pytest.raises(ValueError, match="dataset changed upstream"):
        data.download()


def test_train_registers_and_promotes_only_on_improvement(tracking):
    tr, te = data.split(data.parse(fake_zip()))
    first = train.train_and_register(tr, te, n_trials=3)
    assert first["champion"] and first["metrics"]["f1"] > 0.9 and first["trials"] == 3
    assert len(tracking.search_runs([first["experiment_id"]], "tags.mlflow.parentRunId = '%s'" % first["run_id"])) == 3

    second = train.train_and_register(tr, te, n_trials=3)  # same data and seed: same score
    assert not second["champion"]
    champion = tracking.get_model_version_by_alias(train.MODEL_NAME, "champion")
    assert str(champion.version) == first["version"] and champion.tags["test_f1"] == f"{first['metrics']['f1']:.4f}"

    model = mlflow.pyfunc.load_model(f"models:/{train.MODEL_NAME}@champion")
    pred = model.predict(pd.DataFrame({"text": ["win a free prize now, text WIN", "see you at lunch"]}))
    assert list(pred) == ["spam", "ham"]


def test_promote_ignores_differences_below_the_shown_precision():
    class Version:
        def __init__(self, version, f1):
            self.version, self.tags = version, {"test_f1": f"{f1:.4f}"}

    class Client:
        def __init__(self):
            self.champion, self.tags = Version("1", 0.975903), {}

        def set_model_version_tag(self, name, version, key, value):
            self.tags[version] = value

        def get_model_version_by_alias(self, name, alias):
            return self.champion

        def set_registered_model_alias(self, name, alias, version):
            self.champion = Version(version, float(self.tags[version]))

    c = Client()
    assert not train.promote(c, "2", 0.9759036144578314)  # same score, float noise
    assert c.champion.version == "1" and c.tags["2"] == "0.9759"
    assert train.promote(c, "3", 0.9801)  # a real improvement moves the alias
    assert c.champion.version == "3"


def test_dagster_assets_end_to_end(tracking, monkeypatch):
    monkeypatch.setattr(data, "download", lambda: fake_zip())
    result = dg.materialize(
        [definitions.sms_spam_raw, definitions.sms_spam_split, definitions.triage_model],
        run_config={"ops": {"triage_model": {"config": {"n_trials": 2}}}},
    )
    assert result.success
    meta = result.asset_materializations_for_node("triage_model")[0].metadata
    assert meta["champion"].value is True and meta["trials"].value == 2
    checks = result.get_asset_check_evaluations()
    assert [(c.check_name, c.passed) for c in checks] == [("test_f1_at_least_0_90", True)]


def test_definitions_load_with_a_nightly_schedule():
    defs = definitions.defs
    dg.Definitions.validate_loadable(defs)
    schedule = defs.get_schedule_def("triage_nightly")
    assert schedule.cron_schedule == "0 2 * * *" and schedule.execution_timezone == "Asia/Dubai"
    assert defs.get_job_def("triage_training") is not None

"""Week 5: the BentoML service, the classify_message MCP tool and the Evidently drift report,
with a local SQLite MLflow, a fake S3 and no cluster."""

import asyncio
import io
import json
from datetime import date

import dagster as dg
import mlflow
import pandas as pd
import pytest

import service as serving
import triage_server
from test_triage import fake_zip, tracking  # noqa: F401  (fixture)
from triage import data, definitions, drift, train


class FakeS3:
    """Just enough of boto3's S3 client: put/list/get objects in memory."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_paginator(self, _):
        s3 = self

        class Pages:
            def paginate(self, Bucket, Prefix):
                keys = [k for b, k in s3.objects if b == Bucket and k.startswith(Prefix)]
                return [{"Contents": [{"Key": k} for k in keys]}]

        return Pages()

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


@pytest.fixture
def champion(tracking):  # noqa: F811
    tr, te = data.split(data.parse(fake_zip()))
    train.train_and_register(tr, te, n_trials=2)
    return te


def test_service_classifies_with_the_champion_and_logs_requests(champion, monkeypatch):
    s3 = FakeS3()
    log = serving.RequestLog("")  # no bucket: logging off
    log.bucket, log.s3 = "triage", s3
    monkeypatch.setattr(serving, "RequestLog", lambda bucket: log)
    svc = serving.MessageTriage.inner()
    out = svc.classify(["win a free prize now, text WIN to 80082", "see you at lunch"])
    assert [o["label"] for o in out] == ["spam", "ham"] and out[0]["model_version"] == "1"
    assert 0.5 < out[0]["spam_probability"] <= 1
    log.flush()
    (bucket, key), body = next(iter(s3.objects.items()))
    assert bucket == "triage" and key.startswith(f"requests/{date.today():%Y-%m-%d}/")
    rows = [json.loads(line) for line in body.decode().splitlines()]
    assert [r["label"] for r in rows] == ["spam", "ham"] and rows[0]["text"].startswith("win a free")
    assert svc.model()["version"] == "1"


def test_mcp_tool_explains_the_verdict_and_a_stopped_model_server(monkeypatch):
    assert triage_server.describe({"label": "spam", "spam_probability": 0.97, "model_version": "2"}) == \
        "SPAM: 97% confident (spam probability 0.97, model message-triage v2)"
    assert triage_server.describe({"label": "ham", "spam_probability": 0.1, "model_version": "2"}).startswith(
        "not spam (ham): 90% confident")
    monkeypatch.setattr(triage_server, "TRIAGE_URL", "http://127.0.0.1:9")  # nothing listens there
    assert "mlops profile" in asyncio.run(triage_server.classify_message("hello"))


def test_features_capture_what_spam_looks_like():
    f = drift.features(pd.Series(["WIN £1000 now!! visit www.prize.com", "see you at lunch"]))
    assert list(f["has_url"]) == [1, 0] and list(f["has_money"]) == [1, 0]
    assert f.loc[0, "exclamations"] == 2 and f.loc[0, "upper_ratio"] > f.loc[1, "upper_ratio"]


def test_read_requests_takes_the_last_days_only():
    s3 = FakeS3()
    row = {"ts": "t", "text": "hi", "label": "ham", "spam_probability": 0.1, "model_version": "1"}
    s3.put_object("triage", "requests/2026-10-07/a.jsonl", json.dumps(row).encode())
    s3.put_object("triage", "requests/2026-10-01/b.jsonl", json.dumps(row).encode())  # 6 days earlier
    assert len(drift.read_requests(s3, "triage", today=date(2026, 10, 7), days=3)) == 1
    assert len(drift.read_requests(s3, "triage", today=date(2026, 10, 7), days=7)) == 2


def test_report_flags_a_shifted_stream():
    ref = drift.frame(pd.Series(["see you at lunch", "call me later", "thanks!"] * 40),
                      pd.Series(["ham"] * 120), pd.Series([0.05] * 120))
    cur = drift.frame(pd.Series(["URGENT!! claim your £500 reward at www.win.com now"] * 60),
                      pd.Series(["spam"] * 60), pd.Series([0.97] * 60))
    path, summary = drift.report(ref, cur)
    assert summary["drift_share"] > 0.5 and summary["columns"]["has_url"]["method"]
    assert open(path, encoding="utf-8").read(200).lower().startswith("<!doctype html") or path.endswith(".html")


def test_drift_asset_skips_with_too_few_requests_and_reports_with_enough(champion, monkeypatch):
    s3 = FakeS3()
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: s3)
    split = {"train": champion, "test": champion}

    def run():  # sms_spam_split comes from storage in k3s; here an IO manager hands it over
        return dg.materialize([dg.AssetSpec("sms_spam_split"), definitions.triage_drift_report],
                              resources={"io_manager": _value_io(split)})

    meta = run().asset_materializations_for_node("triage_drift_report")[0].metadata
    assert meta["status"].value.startswith("skipped: 0 requests")

    today = f"{date.today():%Y-%m-%d}"
    rows = [{"ts": "t", "text": "URGENT! win £500 at www.win.com", "label": "spam", "spam_probability": 0.95,
             "model_version": "1"}] * 40
    s3.put_object("triage", f"requests/{today}/x.jsonl", "\n".join(json.dumps(r) for r in rows).encode())
    result = run()
    meta = result.asset_materializations_for_node("triage_drift_report")[0].metadata
    assert meta["n_current"].value == 40 and meta["drift_share"].value > 0.5
    check = result.get_asset_check_evaluations()[0]
    assert check.check_name == "drift_share_at_most_0_5" and not check.passed


def _value_io(value):
    @dg.io_manager
    def load_only():
        class IO(dg.IOManager):
            def handle_output(self, context, obj):
                pass

            def load_input(self, context):
                return value

        return IO()

    return load_only

"""Drift report for the message-triage model (Evidently): do the messages the model sees now
look like the ones it was trained on, and does it answer the same way?

Raw text can't be compared directly, so both sides become the same descriptors (length, digits,
capitals, links, money signs ...) plus the model's own output (spam probability and label).
Reference = the held-out test split scored by the current champion; current = the requests the
BentoML service logged to s3://triage/requests/ over the last WINDOW_DAYS days.
"""

import json
import os
import re
import tempfile
from datetime import date, timedelta

import pandas as pd

WINDOW_DAYS = int(os.environ.get("DRIFT_WINDOW_DAYS", "7"))
MIN_CURRENT = int(os.environ.get("DRIFT_MIN_REQUESTS", "30"))  # fewer: not enough to say anything
URL = re.compile(r"https?://|www\.|\b\w+\.(?:com|net|org|co|uk|ly|io)\b", re.IGNORECASE)
MONEY = re.compile(r"[£$€]|\b(?:AED|USD|EUR|GBP)\b")


def features(texts: pd.Series) -> pd.DataFrame:
    """Per-message descriptors that spam and its drift show up in."""
    t = texts.fillna("").astype(str)
    n = t.str.len().clip(lower=1)
    return pd.DataFrame({
        "length": t.str.len(),
        "words": t.str.split().str.len(),
        "digit_ratio": (t.str.count(r"\d") / n).round(4),
        "upper_ratio": (t.str.count(r"[A-Z]") / n).round(4),
        "exclamations": t.str.count("!"),
        "has_url": t.str.contains(URL).astype(int),
        "has_money": t.str.contains(MONEY).astype(int),
    })


def read_requests(s3, bucket: str, today: date | None = None, days: int = WINDOW_DAYS) -> pd.DataFrame:
    """Logged requests (ts, text, label, spam_probability, model_version) of the last `days` days."""
    today = today or date.today()
    rows = []
    for d in range(days):
        prefix = f"requests/{today - timedelta(days=d):%Y-%m-%d}/"
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read().decode()
                rows += [json.loads(line) for line in body.splitlines() if line.strip()]
    return pd.DataFrame(rows, columns=["ts", "text", "label", "spam_probability", "model_version"])


def frame(texts: pd.Series, labels: pd.Series, proba: pd.Series) -> pd.DataFrame:
    df = features(texts.reset_index(drop=True))
    df["spam_probability"] = proba.reset_index(drop=True).astype(float).round(4)
    df["label"] = labels.reset_index(drop=True).astype(str)
    return df


def report(reference: pd.DataFrame, current: pd.DataFrame) -> tuple[str, dict]:
    """Run Evidently's data-drift preset; returns (path of the HTML report, summary)."""
    from evidently import Report
    from evidently.presets import DataDriftPreset

    snap = Report([DataDriftPreset()]).run(current_data=current, reference_data=reference)
    path = os.path.join(tempfile.mkdtemp(), "drift_report.html")
    snap.save_html(path)
    summary, columns = {}, {}
    for m in snap.dict()["metrics"]:
        kind = m["config"]["type"].rsplit(":", 1)[-1]
        if kind == "DriftedColumnsCount":
            summary = {"drifted_columns": int(m["value"]["count"]), "drift_share": round(float(m["value"]["share"]), 4)}
        elif kind == "ValueDrift":
            columns[m["config"]["column"]] = {"method": m["config"]["method"], "score": round(float(m["value"]), 6),
                                              "threshold": m["config"]["threshold"]}
    return path, {**summary, "columns": columns}

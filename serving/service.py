"""BentoML service for the message-triage model (README §6.15).

    POST /classify  {"texts": ["...", ...]} -> [{"label": "spam"|"ham", "spam_probability", "model_version"}]
    POST /model     {} -> which registry version is loaded

Loads models:/message-triage@champion from MLflow and checks every RECHECK_S seconds whether the
alias moved (the nightly training promoted a better model), reloading without a restart. Every
classified message is appended to s3://triage/requests/ so the drift report (Dagster asset
triage_drift_report) can compare live traffic with the training data.
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import bentoml
import mlflow
import pandas as pd

MODEL_NAME = os.environ.get("MODEL_NAME", "message-triage")
ALIAS = os.environ.get("MODEL_ALIAS", "champion")
RECHECK_S = int(os.environ.get("RECHECK_S", "300"))
LOG_BUCKET = os.environ.get("REQUEST_LOG_BUCKET", "triage")  # "" turns request logging off
FLUSH_S, FLUSH_ROWS = 60, 50

log = logging.getLogger("bentoml.triage")


class RequestLog:
    """Buffers classified messages and writes them to S3 as JSON lines, one object per flush."""

    def __init__(self, bucket: str):
        self.bucket, self.rows, self.lock = bucket, [], threading.Lock()
        if bucket:
            import boto3

            self.s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL"))
            threading.Thread(target=self._timer, daemon=True).start()

    def add(self, rows: list[dict]):
        if not self.bucket:
            return
        with self.lock:
            self.rows += rows
            full = len(self.rows) >= FLUSH_ROWS
        if full:
            self.flush()

    def flush(self):
        with self.lock:
            rows, self.rows = self.rows, []
        if not rows:
            return
        now = datetime.now(timezone.utc)
        key = f"requests/{now:%Y-%m-%d}/{now:%H%M%S}-{uuid.uuid4().hex[:8]}.jsonl"
        try:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body="\n".join(json.dumps(r) for r in rows).encode())
        except Exception as e:  # logging must never break classification
            log.warning("request log flush failed (%d rows dropped): %s", len(rows), e)

    def _timer(self):
        while True:
            time.sleep(FLUSH_S)
            self.flush()


@bentoml.service(name="message_triage", traffic={"timeout": 30})
class MessageTriage:
    def __init__(self):
        self.client = mlflow.MlflowClient()
        self.version = None
        self._load()
        self.requests = RequestLog(LOG_BUCKET)

    def _load(self):
        v = self.client.get_model_version_by_alias(MODEL_NAME, ALIAS)
        # not self.model: that name is the /model API method below
        self.pipeline = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{v.version}")
        self.spam_col = list(self.pipeline.classes_).index("spam")
        self.version, self.checked = str(v.version), time.time()
        log.info("loaded %s v%s (@%s, test_f1 %s)", MODEL_NAME, v.version, ALIAS, v.tags.get("test_f1"))

    def _maybe_reload(self):
        if time.time() - self.checked < RECHECK_S:
            return
        self.checked = time.time()
        try:
            if str(self.client.get_model_version_by_alias(MODEL_NAME, ALIAS).version) != self.version:
                self._load()
        except Exception as e:  # MLflow down: keep serving the model we have
            log.warning("champion check failed, keeping v%s: %s", self.version, e)

    @bentoml.api
    def classify(self, texts: list[str]) -> list[dict]:
        """Classify messages as spam or ham. Returns one result per text, in order."""
        self._maybe_reload()
        proba = self.pipeline.predict_proba(pd.DataFrame({"text": texts}))[:, self.spam_col]
        out = [{"label": "spam" if p >= 0.5 else "ham", "spam_probability": round(float(p), 4),
                "model_version": self.version} for p in proba]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.requests.add([{"ts": now, "text": t, **o} for t, o in zip(texts, out)])
        return out

    @bentoml.api
    def model(self) -> dict:
        """The registry model and version currently loaded."""
        return {"name": MODEL_NAME, "alias": ALIAS, "version": self.version,
                "tracking_uri": mlflow.get_tracking_uri()}

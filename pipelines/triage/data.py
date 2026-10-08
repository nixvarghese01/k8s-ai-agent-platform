"""SMS Spam Collection (UCI, CC BY 4.0): 5,574 English SMS labelled ham/spam, ~13% spam.

Downloaded once per run and checked against a pinned sha256, so every run trains on the same
bytes; the split is stratified with a fixed seed, so test scores are comparable across runs.
"""

import hashlib
import io
import urllib.request
import zipfile

import pandas as pd
from sklearn.model_selection import train_test_split

URL = "https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip"
SHA256 = "1587ea43e58e82b14ff1f5425c88e17f8496bfcdb67a583dbff9eefaf9963ce3"
TEST_SIZE = 0.2
SEED = 42


def download(url: str = URL, sha256: str = SHA256) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise ValueError(f"dataset changed upstream: sha256 {digest}, expected {sha256}")
    return data


def parse(zip_bytes: bytes) -> pd.DataFrame:
    """Columns label ("ham"/"spam") and text; one row per message."""
    raw = zipfile.ZipFile(io.BytesIO(zip_bytes)).read("SMSSpamCollection").decode("utf-8")
    rows = [line.split("\t", 1) for line in raw.splitlines() if line.strip()]
    df = pd.DataFrame(rows, columns=["label", "text"])
    if set(df["label"]) != {"ham", "spam"}:
        raise ValueError(f"unexpected labels: {sorted(set(df['label']))}")
    return df


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train, test = train_test_split(df, test_size=TEST_SIZE, stratify=df["label"], random_state=SEED)
    return train.reset_index(drop=True), test.reset_index(drop=True)

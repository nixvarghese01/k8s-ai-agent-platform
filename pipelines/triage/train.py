"""Train the message-triage classifier (spam vs ham): Optuna tunes a TF-IDF + logistic
regression pipeline, MLflow records every trial and the final model, and the model registry
alias "champion" moves only when the new model beats the current one on the held-out test set.

The model takes a DataFrame with a "text" column and returns "ham"/"spam" (predict_proba too),
so Week 5 can serve models:/message-triage@champion without any code from this repo.
"""

import logging
import os
from datetime import datetime, timezone

import mlflow
import optuna
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, make_scorer, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline

from triage import data

log = logging.getLogger(__name__)

EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT", "message-triage")
MODEL_NAME = os.environ.get("MODEL_NAME", "message-triage")
POSITIVE = "spam"
CV_FOLDS = 5


def make_model(p: dict) -> Pipeline:
    """TF-IDF on words (1-2 grams) or characters (2-5 grams), then logistic regression."""
    if p["analyzer"] == "word":
        tfidf = TfidfVectorizer(analyzer="word", ngram_range=(1, p["word_ngram_max"]), min_df=p["min_df"], sublinear_tf=True)
    else:
        tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, p["char_ngram_max"]), min_df=p["min_df"], sublinear_tf=True)
    return Pipeline([
        # ColumnTransformer takes the "text" column, so the model accepts a DataFrame (what
        # MLflow pyfunc and BentoML pass) instead of a bare list of strings
        ("features", ColumnTransformer([("tfidf", tfidf, "text")])),
        ("clf", LogisticRegression(C=p["C"], class_weight=p["class_weight"], max_iter=2000)),
    ])


def suggest(trial: optuna.Trial) -> dict:
    p = {"analyzer": trial.suggest_categorical("analyzer", ["word", "char_wb"])}
    if p["analyzer"] == "word":
        p["word_ngram_max"] = trial.suggest_int("word_ngram_max", 1, 2)
    else:
        p["char_ngram_max"] = trial.suggest_int("char_ngram_max", 3, 5)
    p["min_df"] = trial.suggest_int("min_df", 1, 3)
    p["C"] = trial.suggest_float("C", 0.1, 100.0, log=True)
    p["class_weight"] = trial.suggest_categorical("class_weight", [None, "balanced"])
    return p


def evaluate(model: Pipeline, test: pd.DataFrame) -> dict:
    y, pred = test["label"], model.predict(test[["text"]])
    proba = model.predict_proba(test[["text"]])[:, list(model.classes_).index(POSITIVE)]
    return {
        "f1": f1_score(y, pred, pos_label=POSITIVE),
        "precision": precision_score(y, pred, pos_label=POSITIVE),
        "recall": recall_score(y, pred, pos_label=POSITIVE),
        "accuracy": accuracy_score(y, pred),
        "roc_auc": roc_auc_score(y == POSITIVE, proba),
    }


def promote(client: MlflowClient, version: str, f1: float, name: str = MODEL_NAME) -> bool:
    """Point the "champion" alias at this version if it beats the current champion's test F1."""
    client.set_model_version_tag(name, version, "test_f1", f"{f1:.4f}")
    try:
        champion = client.get_model_version_by_alias(name, "champion")
    except MlflowException:
        champion = None
    if champion is not None and f1 <= float(champion.tags.get("test_f1", "-1")):
        return False
    client.set_registered_model_alias(name, "champion", version)
    return True


def train_and_register(train: pd.DataFrame, test: pd.DataFrame, n_trials: int = 30,
                       timeout: float | None = None, seed: int = data.SEED) -> dict:
    """Tune, fit, evaluate, log to MLflow, register; returns the run id, version and metrics."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    experiment = mlflow.set_experiment(EXPERIMENT)
    cv = StratifiedKFold(CV_FOLDS, shuffle=True, random_state=seed)
    scorer = make_scorer(f1_score, pos_label=POSITIVE)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    with mlflow.start_run(run_name=f"triage {stamp}") as run:
        mlflow.set_tags({"dataset.url": data.URL, "dataset.sha256": data.SHA256})
        mlflow.log_params({"n_train": len(train), "n_test": len(test), "n_trials": n_trials, "cv_folds": CV_FOLDS,
                           "spam_ratio": round(float((train["label"] == POSITIVE).mean()), 4)})

        def objective(trial: optuna.Trial) -> float:
            p = suggest(trial)
            score = cross_val_score(make_model(p), train[["text"]], train["label"], cv=cv, scoring=scorer).mean()
            with mlflow.start_run(run_name=f"trial {trial.number}", nested=True):
                mlflow.log_params(p)
                mlflow.log_metric("cv_f1", score)
            return score

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
        study.optimize(objective, n_trials=n_trials, timeout=timeout)
        best = suggest(optuna.trial.FixedTrial(study.best_params))
        model = make_model(best).fit(train[["text"]], train["label"])
        metrics = evaluate(model, test)

        mlflow.log_params({f"best.{k}": v for k, v in best.items()})
        mlflow.log_metric("cv_f1", study.best_value)
        mlflow.log_metrics({f"test_{k}": v for k, v in metrics.items()})
        cm = confusion_matrix(test["label"], model.predict(test[["text"]]), labels=["ham", POSITIVE])
        mlflow.log_dict({"labels": ["ham", POSITIVE], "rows_true_cols_pred": cm.tolist()}, "confusion_matrix.json")

        example = test[["text"]].head(3)
        info = mlflow.sklearn.log_model(
            model, name="model", signature=infer_signature(example, model.predict(example)),
            input_example=example, registered_model_name=MODEL_NAME,
        )
        version = str(info.registered_model_version)
        promoted = promote(MlflowClient(), version, metrics["f1"])
        log.info("run %s: version %s, test F1 %.4f, champion=%s", run.info.run_id, version, metrics["f1"], promoted)

    return {"run_id": run.info.run_id, "experiment_id": experiment.experiment_id, "version": version,
            "champion": promoted, "best_params": best, "cv_f1": study.best_value, "trials": len(study.trials),
            "metrics": metrics}

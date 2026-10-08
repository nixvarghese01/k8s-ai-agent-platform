"""Golden-set evaluation (issue #29): how well the current model of each use case does, so a
model change is decided on numbers, not on a feeling.

    python evaluation.py            run every question, print the results, save the summary
    python evaluation.py <id> ...   just those questions, with their answers; not saved
    (Models page -> Evaluate)       the same, with a progress bar

Questions and checks: golden.yaml. Each use case is asked the way it's used:
    agent  POST /chat on the agent (tools, documents, memory, web)
    chat   LiteLLM chat-default, no system prompt (like Open WebUI)
    email  LiteLLM chat-email with n8n's triage prompt and JSON output (like workflow 4)
Results: the last 20 summaries in ConfigMap llm/llm-model (key "evals") for the Models page,
and an MLflow run in experiment "llm-evaluation" with every answer, when MLflow is up.
"""

import json
import os
import re
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import yaml

import models

AGENT_URL = os.environ.get("AGENT_URL", "http://agent.agent.svc.cluster.local:8000")
MLFLOW_URL = os.environ.get("MLFLOW_URL", "http://mlflow.mlops.svc.cluster.local:5000")
GOLDEN = Path(__file__).with_name("golden.yaml")
TZ = ZoneInfo(os.environ.get("AGENT_TZ", "Asia/Dubai"))
KEEP = 20  # summaries kept in the ConfigMap
WORSE_BY = 0.10  # a score this much below the best known for the use case gets a warning
# Keep in sync with the "Categorise + summarise (LLM)" node in automation/n8n-workflows.yaml
EMAIL_PROMPT = ('You sort e-mail. Reply with JSON only: {"category": one of work, personal, billing, newsletter, '
                'other; "summary": one short sentence; "needs_reply": true or false}.')


def golden() -> dict:
    return yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))


# ---- asking --------------------------------------------------------------------------------
def ask_agent(message: str, thread: str) -> tuple[str, list[str]]:
    d = httpx.post(f"{AGENT_URL}/chat", json={"message": message, "thread_id": thread}, timeout=900).json()
    return d["answer"], [s["tool"] for s in d["steps"]]


def ask_llm(alias: str, message: str, system: str | None = None, as_json: bool = False) -> str:
    body = {"model": alias, "temperature": 0,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": message}]}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{models.LITELLM_URL}/v1/chat/completions", json=body, timeout=600,
                   headers={"Authorization": "Bearer sk-local"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ask(item: dict) -> tuple[str, list[str]]:
    if item["use_case"] == "agent":
        thread = f"eval-{uuid.uuid4()}"
        for msg in item.get("setup", []):
            ask_agent(msg, thread)
        try:
            return ask_agent(item["ask"], f"eval-{uuid.uuid4()}")  # a new conversation: memory, not history
        finally:
            for msg in item.get("teardown", []):
                ask_agent(msg, thread)
    if item["use_case"] == "email":
        return ask_llm("chat-email", item["ask"], EMAIL_PROMPT, as_json=True), []
    return ask_llm("chat-default", item["ask"]), []


# ---- scoring -------------------------------------------------------------------------------
def check(expect: dict, answer: str, tools: list[str], seconds: float, now: datetime | None = None) -> dict:
    """Which checks failed (empty = passed), whether it was slow, or why it was skipped."""
    now = now or datetime.now(TZ)
    low = answer.lower()
    if any(s.lower() in low for s in expect.get("skip_if", [])):
        return {"skipped": "a profile is off", "failed": [], "slow": False}
    fill = lambda s: s.replace("{weekday}", now.strftime("%A")).lower()
    failed = [f"missing {s!r}" for s in expect.get("all", []) if fill(s) not in low]
    if expect.get("any") and not any(fill(s) in low for s in expect["any"]):
        failed.append(f"none of {expect['any']}")
    if expect.get("tool") and not any(t.startswith(expect["tool"]) for t in tools):
        failed.append(f"no {expect['tool']} step (tools: {tools or 'none'})")
    if expect.get("json"):
        try:
            data = json.loads(re.sub(r"^```(json)?|```$", "", answer.strip()).strip())
            missing = [k for k in expect["json"] if k not in data]
            if missing:
                failed.append(f"JSON without {missing}")
        except (ValueError, TypeError):
            failed.append("not JSON")
    if expect.get("max_words") and len(re.findall(r"\S+", answer)) > expect["max_words"]:
        failed.append(f"more than {expect['max_words']} words")
    return {"skipped": None, "failed": failed, "slow": seconds > expect.get("max_seconds", 1e9)}


def run_one(item: dict) -> dict:
    start = time.time()
    try:
        answer, tools = ask(item)
        error = None
    except Exception as e:
        answer, tools, error = "", [], f"{type(e).__name__}: {e}"
    seconds = round(time.time() - start, 1)
    result = check(item["expect"], answer, tools, seconds)
    if error:
        result["failed"] = [error]
    return {"id": item["id"], "use_case": item["use_case"], "seconds": seconds, "tools": tools,
            "answer": answer[:1500], **result, "passed": not result["skipped"] and not result["failed"]}


def summarise(results: list[dict], choice: dict[str, str], version: int) -> dict:
    by_uc = {}
    for uc in models.USE_CASES:
        rs = [r for r in results if r["use_case"] == uc and not r["skipped"]]
        if rs:
            by_uc[uc] = {"model": choice[uc], "passed": sum(r["passed"] for r in rs), "total": len(rs),
                         "score": round(sum(r["passed"] for r in rs) / len(rs), 2)}
    done = [r for r in results if not r["skipped"]]
    return {"at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "set_version": version, "choice": choice,
            "score": round(sum(r["passed"] for r in done) / len(done), 2) if done else None,
            "by_use_case": by_uc, "median_s": statistics.median(r["seconds"] for r in done) if done else None,
            "slow": sum(r["slow"] for r in done), "skipped": [r["id"] for r in results if r["skipped"]],
            "failed": [r["id"] for r in done if not r["passed"]]}


def run(kube: models.Kube, progress=None, only: list[str] | None = None) -> tuple[dict, list[dict]]:
    """Ask every golden question with the current models; save and return (summary, results).
    `only` runs just those ids, to check a fix; such partial runs aren't saved."""
    g = golden()
    choice = kube.choice()
    items = [i for i in g["items"] if not only or i["id"] in only]
    results = []
    for i, item in enumerate(items):
        if progress:
            progress(i, len(items), item)
        results.append(run_one(item))
    summary = summarise(results, choice, g["version"])
    if not only:
        save(kube, summary)
        summary["mlflow_run"] = log_mlflow(summary, results)
    return summary, results


# ---- keeping results -----------------------------------------------------------------------
def history(kube: models.Kube) -> list[dict]:
    try:
        return json.loads(kube._data().get("evals") or "[]")
    except ValueError:
        return []


def save(kube: models.Kube, summary: dict) -> None:
    kube.update(lambda d: d | {"evals": json.dumps((json.loads(d.get("evals") or "[]") + [summary])[-KEEP:])})


def best(evals: list[dict], use_case: str, version: int) -> dict | None:
    """The best score a use case has had on this question set (and with which model)."""
    scored = [(e["by_use_case"][use_case]["score"], e["at"], e["by_use_case"][use_case]["model"])
              for e in evals if e.get("set_version") == version and use_case in e.get("by_use_case", {})]
    if not scored:
        return None
    score, at, model = max(scored)
    return {"score": score, "at": at, "model": model}


def worse_than_best(summary: dict, evals: list[dict]) -> list[str]:
    """Use cases that scored clearly worse than their best on the same question set."""
    out = []
    for uc, s in summary["by_use_case"].items():
        b = best(evals, uc, summary["set_version"])
        if b and s["score"] < b["score"] - WORSE_BY:
            out.append(f"{models.USE_CASES[uc][0]}: {s['score']:.0%} with {s['model']}, "
                       f"best was {b['score']:.0%} with {b['model']} ({b['at']})")
    return out


def model_scores(evals: list[dict]) -> dict[tuple[str, str], float]:
    """(use case, model) -> its latest score, for the Models page's dropdowns."""
    out = {}
    for e in evals:
        for uc, s in e.get("by_use_case", {}).items():
            out[(uc, s["model"])] = s["score"]
    return out


def log_mlflow(summary: dict, results: list[dict]) -> str | None:
    """An MLflow run with the scores, the models and every answer; None if MLflow is off."""
    api = f"{MLFLOW_URL}/api/2.0/mlflow"
    try:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{api}/experiments/get-by-name", params={"experiment_name": "llm-evaluation"})
            exp = r.json()["experiment"]["experiment_id"] if r.status_code == 200 else \
                c.post(f"{api}/experiments/create", json={"name": "llm-evaluation"}).json()["experiment_id"]
            run = c.post(f"{api}/runs/create", json={"experiment_id": exp, "run_name": summary["at"],
                                                     "start_time": int(time.time() * 1000)}).json()["run"]
            run_id = run["info"]["run_id"]
            metrics = [{"key": "score", "value": summary["score"] or 0}] + [
                {"key": f"score_{uc}", "value": s["score"]} for uc, s in summary["by_use_case"].items()] + [
                {"key": "median_seconds", "value": summary["median_s"] or 0}, {"key": "slow", "value": summary["slow"]}]
            stamp = int(time.time() * 1000)
            c.post(f"{api}/runs/log-batch", json={
                "run_id": run_id, "metrics": [m | {"timestamp": stamp, "step": 0} for m in metrics],
                "params": [{"key": f"model_{uc}", "value": m} for uc, m in summary["choice"].items()]
                + [{"key": "set_version", "value": str(summary["set_version"])}]})
            artifact = run["info"]["artifact_uri"].removeprefix("mlflow-artifacts:/")
            c.put(f"{MLFLOW_URL}/api/2.0/mlflow-artifacts/artifacts/{artifact}/results.json",
                  content=json.dumps({"summary": summary, "results": results}, indent=1))
            c.post(f"{api}/runs/update", json={"run_id": run_id, "status": "FINISHED", "end_time": int(time.time() * 1000)})
            return run_id
    except (httpx.HTTPError, KeyError, ValueError):
        return None


if __name__ == "__main__":
    def show(i, n, item):
        print(f"[{i + 1}/{n}] {item['use_case']:5} {item['id']}", flush=True)

    only = sys.argv[1:]  # question ids: run just those, without saving
    summary, results = run(models.Kube(), progress=show, only=only)
    for r in results:
        mark = "SKIP" if r["skipped"] else "PASS" if r["passed"] else "FAIL"
        print(f"{mark}  {r['use_case']:5} {r['id']:18} {r['seconds']:6.1f}s{'  slow' if r['slow'] else ''}"
              f"  {'; '.join(r['failed'])}")
        if only:
            print("   ", r["tools"], r["answer"][:400].replace("\n", " "))
    print(json.dumps({k: summary.get(k) for k in ("score", "by_use_case", "median_s", "slow", "skipped", "mlflow_run")}, indent=1))

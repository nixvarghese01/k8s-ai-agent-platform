"""The golden-set evaluation (ui/evaluation.py): the set itself, the checks, and the history."""

from datetime import datetime

import pytest

import evaluation
import models

KNOWN = {"all", "any", "tool", "json", "max_words", "max_seconds", "skip_if"}


def test_golden_set_is_well_formed():
    g = evaluation.golden()
    ids = [i["id"] for i in g["items"]]
    assert isinstance(g["version"], int) and len(ids) == len(set(ids)) >= 20
    for item in g["items"]:
        assert item["use_case"] in models.USE_CASES and item["ask"].strip()
        assert set(item["expect"]) <= KNOWN and set(item["expect"]) - {"max_seconds", "skip_if"}, item["id"]
    assert {i["use_case"] for i in g["items"]} == set(models.USE_CASES)


THURSDAY = datetime(2026, 10, 8, 9, 0)


@pytest.mark.parametrize("expect, answer, tools, failed", [
    ({"all": ["0 EUR"], "any": ["open source"]}, "Budget: 0 EUR, all open source.", [], []),
    ({"any": ["1 November", "2026-11-01"]}, "It renews on 2026-11-01.", [], []),
    ({"any": ["cooling stand"]}, "Buy a fan.", [], ["none of ['cooling stand']"]),
    ({"tool": "list_dir"}, "files", ["search_documents (auto)"], ["no list_dir step (tools: ['search_documents (auto)'])"]),
    ({"tool": "recall"}, "lighthouse", ["recall (auto)"], []),
    ({"all": ["{weekday}"]}, "Today is Thursday.", [], []),
    ({"json": ["category"], "any": ['"work"']}, '```json\n{"category": "work"}\n```', [], []),
    ({"json": ["category", "needs_reply"]}, '{"category": "work"}', [], ["JSON without ['needs_reply']"]),
    ({"json": ["city"]}, "Paris, France", [], ["not JSON"]),
    ({"any": ["blue"], "max_words": 1}, "The sky is blue.", [], ["more than 1 words"]),
])
def test_checks(expect, answer, tools, failed):
    assert evaluation.check(expect, answer, tools, 5.0, now=THURSDAY)["failed"] == failed


def test_slow_is_reported_and_off_profiles_are_skipped():
    r = evaluation.check({"any": ["x"], "max_seconds": 10}, "x", [], 12.0, now=THURSDAY)
    assert r["slow"] and r["failed"] == []
    r = evaluation.check({"any": ["spam"], "skip_if": ["mlops profile"]}, "It's part of the mlops profile.", [], 1, now=THURSDAY)
    assert r["skipped"] and r["failed"] == []


def result(uc, passed, skipped=None, seconds=10.0):
    return {"id": f"{uc}-{passed}-{seconds}", "use_case": uc, "passed": passed, "skipped": skipped,
            "seconds": seconds, "slow": False, "failed": [] if passed else ["x"]}


def test_summary_per_use_case_ignores_skipped():
    choice = {"chat": "a", "agent": "a", "email": "b"}
    rs = [result("agent", True), result("agent", False), result("agent", False, skipped="off"),
          result("chat", True), result("email", True, seconds=20.0)]
    s = evaluation.summarise(rs, choice, 1)
    assert s["score"] == 0.75 and s["median_s"] == 10.0 and len(s["skipped"]) == 1
    assert s["by_use_case"]["agent"] == {"model": "a", "passed": 1, "total": 2, "score": 0.5}
    assert s["by_use_case"]["email"]["model"] == "b"


def summary(at, agent_model, agent_score, version=1):
    return {"at": at, "set_version": version, "choice": {"chat": "a", "agent": agent_model, "email": "a"},
            "by_use_case": {"agent": {"model": agent_model, "score": agent_score, "passed": 0, "total": 0}}}


def test_a_clearly_worse_score_is_flagged_against_the_best_on_the_same_set():
    evals = [summary("2026-10-08 10:00", "qwen2.5:3b", 0.86), summary("2026-10-01 10:00", "old", 0.99, version=0)]
    assert evaluation.best(evals, "agent", 1) == {"score": 0.86, "at": "2026-10-08 10:00", "model": "qwen2.5:3b"}
    worse = evaluation.worse_than_best(summary("2026-10-08 12:00", "llama3.2:3b", 0.60), evals)
    assert len(worse) == 1 and "60% with llama3.2:3b, best was 86% with qwen2.5:3b" in worse[0]
    assert evaluation.worse_than_best(summary("2026-10-08 12:00", "qwen3:4b", 0.80), evals) == []  # within 10 points
    assert evaluation.model_scores(evals + [summary("x", "qwen3:4b", 0.9)])[("agent", "qwen3:4b")] == 0.9

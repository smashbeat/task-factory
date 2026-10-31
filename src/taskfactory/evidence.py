"""An evidence pack: what a task's generator built and what happened when agents ran on it.

Layout, as Harbor and the coa-intake tooling leave it:
  manifest.json                 the generator's record of every item: route, house, features
  results/static-checks.txt     PASS or FAIL per static check
  results/rubric/*.json         one implementation-rubric run per file
  results/<job>/<trial>/        reward.txt, ctrf.json and trial.json (agent, model, times)
The job name says what the trial was: standard, cheat, oracle or nop.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from .diffs import Diff, parse_diff

KINDS = ("cheat", "oracle", "nop", "standard")


@dataclass(frozen=True)
class Item:
    id: str
    route: str
    house: str
    features: tuple[str, ...]


@dataclass
class Trial:
    name: str
    job: str
    kind: str
    agent: str | None
    model: str | None
    effort: str | None
    reward: float
    total: int
    correct: int
    failed: dict[str, list[Diff]]
    minutes: float | None
    exception: str | None


@dataclass
class Pack:
    root: Path
    items: dict[str, Item]
    sample_features: frozenset[str]
    trials: list[Trial]
    static_checks: list[tuple[str, bool]] = field(default_factory=list)
    rubric_runs: list[dict[str, str]] = field(default_factory=list)

    def trial(self, short: str) -> Trial:
        return next(t for t in self.trials if t.name.endswith(short))


def _kind(job: str) -> str:
    return next((k for k in KINDS if k in job), "standard")


def _diff_lines(trace: str) -> list[str]:
    lines = []
    for raw in trace.splitlines():
        if not raw.startswith("E  ") or "assert not" in raw:
            continue
        lines.append(raw[1:].strip().removeprefix("AssertionError: "))
    return lines


def _minutes(started: str | None, finished: str | None) -> float | None:
    if not (started and finished):
        return None
    a, b = (dt.datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (started, finished))
    return (b - a).total_seconds() / 60


def _trial(d: Path) -> Trial:
    meta = json.loads((d / "trial.json").read_text()) if (d / "trial.json").exists() else {}
    reward = float((d / "reward.txt").read_text().strip() or 0) if (d / "reward.txt").exists() else 0.0
    tests = json.loads((d / "ctrf.json").read_text())["results"]["tests"] if (d / "ctrf.json").exists() else []
    failed = {
        t["name"].rsplit("_", 1)[-1]: [parse_diff(x) for x in _diff_lines(t.get("trace", ""))]
        for t in tests
        if t["status"] != "passed"
    }
    return Trial(
        name=d.name,
        job=d.parent.name,
        kind=_kind(d.parent.name),
        agent=meta.get("agent"),
        model=meta.get("model"),
        effort=meta.get("effort"),
        reward=reward,
        total=len(tests),
        correct=len(tests) - len(failed),
        failed=failed,
        minutes=_minutes(meta.get("started"), meta.get("finished")),
        exception=meta.get("exception"),
    )


def load_pack(root: Path, manifest: str = "manifest.json") -> Pack:
    root = Path(root)
    m = json.loads((root / manifest).read_text())
    items = {
        h["id"]: Item(h["id"], h["route"], h["house"], tuple(h["features"])) for h in m["hidden"]
    }
    sample_features = frozenset(f for s in m.get("samples", []) for f in s["features"])
    results = root / "results"
    trials = [
        _trial(d)
        for job in sorted(results.iterdir())
        if job.is_dir() and job.name != "rubric"
        for d in sorted(job.iterdir())
        if d.is_dir() and ((d / "reward.txt").exists() or (d / "ctrf.json").exists())
    ]
    checks = []
    sc = results / "static-checks.txt"
    if sc.exists():
        for line in sc.read_text().splitlines():
            if line.startswith(("PASS ", "FAIL ")):
                checks.append((line[5:].strip(), line.startswith("PASS")))
    rubric = [
        {k: v["outcome"] for k, v in json.loads(f.read_text())["checks"].items()}
        for f in sorted((results / "rubric").glob("*.json"))
    ] if (results / "rubric").exists() else []
    return Pack(root, items, sample_features, trials, checks, rubric)

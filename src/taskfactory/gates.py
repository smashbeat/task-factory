"""The gates. Each reads the evidence pack and returns a verdict that a person can act on.

A gate passes, warns, or fails. A failure names the stage the task goes back to: the spec (instruction and
rules), the generator, the verifier, the environment, or the design itself when the task is simply too easy.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .attribution import Attribution, Profile, attribute_trial
from .evidence import Pack, Trial

THIN_MARGIN = 0.9


@dataclass(frozen=True)
class Finding:
    level: str  # fail, warn, info
    text: str


@dataclass
class GateResult:
    gate: str
    title: str
    status: str  # pass, warn, fail
    findings: list[Finding] = field(default_factory=list)
    send_back: str | None = None
    attributions: dict[str, list[Attribution]] = field(default_factory=dict)


def _result(gate: str, title: str, findings: list[Finding], send_back: str | None) -> GateResult:
    levels = {f.level for f in findings}
    status = "fail" if "fail" in levels else "warn" if "warn" in levels else "pass"
    return GateResult(gate, title, status, findings, send_back if status == "fail" else None)


def _short(t: Trial) -> str:
    return t.name.split("__")[-1]


def _standard(pack: Pack) -> list[Trial]:
    return [t for t in pack.trials if t.kind == "standard"]


def quality(pack: Pack, profile: Profile) -> GateResult:
    f: list[Finding] = []
    send = None
    oracles = [t for t in pack.trials if t.kind == "oracle"]
    nops = [t for t in pack.trials if t.kind == "nop"]
    if not oracles:
        f.append(Finding("warn", "no oracle run in the evidence"))
    for t in oracles:
        ok = t.reward == 1
        f.append(Finding("info" if ok else "fail", f"oracle {_short(t)}: reward {t.reward:g}, {t.correct} of {t.total}"))
        send = send or (None if ok else "verifier")
    if not nops:
        f.append(Finding("warn", "no nop run in the evidence"))
    for t in nops:
        ok = t.reward == 0
        f.append(Finding("info" if ok else "fail", f"nop {_short(t)}: reward {t.reward:g}"))
        send = send or (None if ok else "verifier")
    if pack.static_checks:
        bad = [n for n, ok in pack.static_checks if not ok]
        f.append(Finding("fail" if bad else "info", f"static checks: {len(pack.static_checks) - len(bad)} of {len(pack.static_checks)} pass" + (f" (failing: {', '.join(bad)})" if bad else "")))
        send = send or ("spec" if bad else None)
    else:
        f.append(Finding("warn", "no static checks in the evidence"))
    if pack.rubric_runs:
        failing = Counter(k for run in pack.rubric_runs for k, v in run.items() if v == "fail")
        n = len(pack.rubric_runs)
        crit = len(pack.rubric_runs[0])
        if failing:
            worst = ", ".join(f"{k} ({c} of {n})" for k, c in failing.most_common())
            f.append(Finding("fail", f"implementation rubric: failing {worst}"))
            send = send or "spec"
        else:
            f.append(Finding("info", f"implementation rubric: {n} runs, every one of {crit} criteria pass or not applicable"))
    else:
        f.append(Finding("warn", "no implementation rubric runs in the evidence"))
    return _result("quality", "Quality: does the task do what it claims, every time?", f, send)


def difficulty(pack: Pack, profile: Profile) -> GateResult:
    f: list[Finding] = []
    trials = _standard(pack)
    if not trials:
        return _result("difficulty", "Difficulty: do strong agents fail?", [Finding("fail", "no standard trials")], "design")
    solved = [t for t in trials if t.reward > 0]
    for t in solved:
        f.append(Finding("fail", f"{t.agent} ({t.model}) solved it in trial {_short(t)}"))
    by_agent: dict[str, list[Trial]] = {}
    for t in trials:
        by_agent.setdefault(t.agent or "?", []).append(t)
    for agent, ts in by_agent.items():
        scores = ", ".join(str(t.correct) for t in ts)
        mins = [t.minutes for t in ts if t.minutes is not None]
        span = f", {min(mins):.0f} to {max(mins):.0f} min per trial" if mins else ""
        f.append(Finding("info", f"{agent} ({ts[0].model}, {ts[0].effort}): {len(ts) - sum(t.reward > 0 for t in ts)} of {len(ts)} failed; items right {scores} of {ts[0].total}{span}"))
    if len(by_agent) < 2:
        f.append(Finding("warn", "only one agent family ran; difficulty from one family can be that family's blind spot"))
    best = max(trials, key=lambda t: t.correct / max(t.total, 1))
    if best.total and best.correct / best.total >= THIN_MARGIN and not solved:
        f.append(Finding("warn", f"thin margin: the best trial got {best.correct} of {best.total} ({best.agent}, {_short(best)}); replay its program on fresh seeds before shipping"))
    return _result("difficulty", "Difficulty: do strong agents fail?", f, "design" if solved else None)


def _policy_rules(pack: Pack, profile: Profile) -> set[int]:
    p = pack.root / profile.policy
    if not p.exists():
        return set()
    return {int(m[1]) for m in re.finditer(r"^(\d+)\.\s", p.read_text(), re.M)}


def fairness(pack: Pack, profile: Profile) -> GateResult:
    f: list[Finding] = []
    send = None
    trials = _standard(pack)
    written = _policy_rules(pack, profile)
    atts = {t.name: attribute_trial(t, pack, profile) for t in trials}
    for t in trials:
        a = atts[t.name]
        rule = [x for x in a if x.kind == "rule"]
        unexplained = [x for x in a if x.kind == "unexplained"]
        reading = [x for x in a if x.kind == "reading"]
        if rule:
            f.append(Finding("info", f"{_short(t)} ({t.agent}): {len(rule)} rule-decided ({', '.join(x.item for x in rule)}), {len(reading)} reading"))
        elif a:
            f.append(Finding("fail", f"{_short(t)} ({t.agent}) failed only on reading misses; its failure rests on the page, not on a rule"))
            send = send or "design"
        if unexplained:
            f.append(Finding("warn", f"{_short(t)}: {', '.join(x.item for x in unexplained)} unexplained; send to the judge"))
    fired = [x for a in atts.values() for x in a if x.kind == "rule"]
    missing = sorted({r for x in fired for r in x.rules if written and r not in written})
    if missing:
        f.append(Finding("fail", f"failures cite rules {missing} that the policy does not state"))
        send = send or "spec"
    shown: dict[str, set[int]] = {}
    for x in fired:
        for feat in x.features:
            if feat not in pack.sample_features:
                shown.setdefault(feat, set()).update(x.rules)
    for feat, rules in sorted(shown.items()):
        nums = sorted(rules)
        cited = f"rule {nums[0]} is" if len(nums) == 1 else f"rules {', '.join(map(str, nums[:-1]))} and {nums[-1]} are"
        f.append(Finding("warn", f"{cited} written, but no sample shows '{feat}'; agents meet it first on hidden items"))
    for item in sorted(pack.items):
        if trials and all(item in t.failed for t in trials):
            f.append(Finding("warn", f"{item}: no trial got it right; check it is reachable before shipping"))
    r = _result("fairness", "Fairness: when agents fail, is it their fault?", f, send)
    r.attributions = atts
    return r


def cheat(pack: Pack, profile: Profile) -> GateResult:
    f: list[Finding] = []
    trials = [t for t in pack.trials if t.kind == "cheat"]
    if not trials:
        f.append(Finding("warn", "no cheat trial in the evidence"))
    beaten = False
    for t in trials:
        ok = t.reward == 0
        beaten |= not ok
        note = f" ({t.exception})" if t.exception else ""
        f.append(Finding("info" if ok else "fail", f"{t.agent} cheat trial {_short(t)}: reward {t.reward:g}{note}"))
    return _result("cheat", "Cheat: can an agent get the reward without doing the work?", f, "environment" if beaten else None)


GATES = (quality, difficulty, fairness, cheat)

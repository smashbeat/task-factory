"""The build loop: gate each stage, send failures back, retry within a budget, write what passed.

Stages so far: pack, plan, spec, corpus. A failure sent back to the plan is retried with a fresh composition,
up to two times. A failure sent back to the pack stops the build: rules and features need an author.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .corpus import Corpus, make_corpus
from .gates import corpus_gate, pack_gate, spec_gate
from .pack import Domain, load_domain
from .plan import Plan, make_plan

RETRIES = 2


@dataclass
class BuildRun:
    pack: str
    seed: int
    verdict: str = "stopped"
    stopped_at: str | None = None
    log: list[dict] = field(default_factory=list)
    plan: Plan | None = None
    corpus: Corpus | None = None


def _record(run: BuildRun, stage: str, attempt: int, g) -> None:
    run.log.append({
        "stage": stage, "attempt": attempt, "status": g.status, "send_back": g.send_back,
        "findings": [{"level": x.level, "text": x.text} for x in g.findings],
    })


def policy_text(pack: Domain) -> str:
    lines = [f"{pack.item.capitalize()} intake policy (normative)", ""]
    for r in pack.rules:
        lines += [f"{r.id}. {r.title}. {r.text}", ""]
    return "\n".join(lines)


def instruction_text(pack: Domain, plan: Plan) -> str:
    tpl = (pack.root / "instruction.md").read_text()
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
             "twelve", "thirteen", "fourteen", "fifteen", "sixteen"]
    n = len(plan.samples)
    return tpl.format(samples=words[n] if n < len(words) else str(n))


def _write(out: Path, pack: Domain, plan: Plan, corpus: Corpus, run: BuildRun) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "policy.md").write_text(policy_text(pack))
    (out / "instruction.md").write_text(instruction_text(pack, plan))
    manifest = {
        "pack": pack.name, "seed": plan.seed, "plan_attempt": plan.attempt,
        "samples": [_item(i, corpus) for i in plan.samples],
        "hidden": [_item(i, corpus) for i in plan.hidden],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    for sub in ("truth", "specs", "mutants"):
        (out / sub).mkdir(exist_ok=True)
    for i in plan.samples + plan.hidden:
        (out / "truth" / f"{i.id}.json").write_text(json.dumps(corpus.truth[i.id], indent=1, ensure_ascii=False))
        (out / "specs" / f"{i.id}.json").write_text(json.dumps(corpus.specs[i.id], indent=1, ensure_ascii=False))
        (out / "mutants" / f"{i.id}.json").write_text(json.dumps({str(r): a for r, a in corpus.mutants[i.id].items()}, indent=1, ensure_ascii=False))
    (out / "build.json").write_text(json.dumps({"verdict": run.verdict, "log": run.log}, indent=1))


def _item(i, corpus: Corpus) -> dict:
    return {"id": i.id, "house": i.style, "route": i.route, "units": i.units, "features": sorted(i.features),
            "rules_decided": sorted(corpus.mutants[i.id])}


def build(pack_dir: Path, seed: int, out: Path, planner: Callable = make_plan) -> BuildRun:
    pack = load_domain(pack_dir)
    run = BuildRun(pack.name, seed)
    g = pack_gate(pack)
    _record(run, "pack", 0, g)
    if g.status == "fail":
        run.stopped_at = "pack"
        return run
    for attempt in range(RETRIES + 1):
        plan = planner(pack, seed, attempt)
        g = spec_gate(pack, plan)
        _record(run, "spec", attempt, g)
        if g.status == "fail":
            run.stopped_at = "spec"
            if g.send_back == "plan":
                continue
            return run
        corpus = make_corpus(pack, plan, seed)
        g = corpus_gate(pack, plan, corpus, seed)
        _record(run, "corpus", attempt, g)
        if g.status == "fail":
            run.stopped_at = "corpus"
            if g.send_back == "plan":
                continue
            return run
        run.stopped_at = None
        run.plan, run.corpus = plan, corpus
        warned = any(x["status"] == "warn" for x in run.log if x["attempt"] == attempt or x["stage"] == "pack")
        run.verdict = "ready to render, with warnings" if warned else "ready to render"
        _write(Path(out), pack, plan, corpus, run)
        return run
    run.verdict = "stopped"
    return run

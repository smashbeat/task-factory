"""The build loop: gate each stage, send failures back, retry within a budget, write what passed.

Stages so far: pack, plan, spec, corpus. A failure sent back to the plan is retried with a fresh composition,
up to two times. A failure sent back to the pack stops the build: rules and features need an author.
"""
from __future__ import annotations

import json
import textwrap
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
        body = textwrap.fill(f"{r.id}. {r.title}. {r.text}", width=113, subsequent_indent="   ")
        lines += [body, ""]
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


def build(pack_dir: Path, seed: int, out: Path, planner: Callable = make_plan, docker: bool = False,
          task_dir: Path | None = None, fix: bool = False, fix_model: str | None = None,
          start_from: Path | None = None) -> BuildRun:
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
        if docker:
            _docker_stages(run, pack, Path(out), task_dir, fix, fix_model, start_from)
        return run
    run.verdict = "stopped"
    return run


def _docker_stages(run: BuildRun, pack: Domain, out: Path, task_dir: Path | None, fix: bool = False,
                   fix_model: str | None = None, start_from: Path | None = None) -> None:
    import shutil

    from . import docker
    from .assemble import assemble
    from .gates import render_gate

    try:
        docker.render(pack, out)
    except Exception as e:
        run.log.append({"stage": "render", "attempt": 0, "status": "fail", "send_back": "pack",
                        "findings": [{"level": "fail", "text": str(e)}]})
        run.verdict, run.stopped_at = "stopped", "render"
        return
    g = render_gate(out)
    _record(run, "render", 0, g)
    if g.status == "fail":
        run.verdict, run.stopped_at = "stopped", "render"
        return
    ref_file = pack.root / "task" / "solution" / "intake.py"
    candidate: Path | None = None   # an agent's fix stays a candidate until a seed it never saw passes
    if start_from:                   # resume from an earlier run's candidate instead of the pack's reference
        candidate = out / "candidate-start.py"
        shutil.copy(start_from, candidate)
    train = [out]                    # every seed the agent has seen; a failed holdout joins it
    for rnd in range(1, HOLDOUT_ROUNDS + 1):
        candidate = _fix_until_pass(run, pack, train, candidate, fix, fix_model)
        if candidate is False:
            run.verdict, run.stopped_at = "stopped", "reference"
            return
        if candidate is None:        # the pack's own reference passed untouched
            break
        hold = _holdout(run, pack, out, candidate, rnd)
        if hold is None:
            break
        if not fix or rnd == HOLDOUT_ROUNDS or not (hold / "reference.json").exists():
            run.verdict, run.stopped_at = "stopped", "holdout"
            return
        train.append(hold)
    if candidate:
        shutil.copy(candidate, ref_file)
    name = f"{pack.name}-s{run.seed}"
    assemble(pack, out, task_dir or out / "task" / name, name)
    run.verdict = "task assembled, ready for trials"
    (out / "build.json").write_text(json.dumps({"verdict": run.verdict, "log": run.log}, indent=1))


def _fix_until_pass(run: BuildRun, pack: Domain, train: list[Path], candidate: Path | None, fix: bool,
                    fix_model: str | None):
    """Run the reference on every seed seen so far and send failures to the fixing agent. Returns the
    candidate (None if the pack's reference passed untouched), or False when the stage stops."""
    import shutil

    from . import docker
    from .agent import fix_reference
    from .gates import Finding, reference_gate

    for attempt in range(RETRIES + 1):
        failed = False
        for d in train:
            try:
                docker.reference(pack, d, solution=candidate)
            except Exception as e:
                (d / "reference.json").write_text("[]")
                run.log.append({"stage": "reference", "attempt": attempt, "status": "fail", "send_back": None,
                                "findings": [{"level": "fail", "text": f"reference could not run on {d.name}: {e}"}]})
            g = reference_gate(d)
            if d != train[0]:
                g.findings.insert(0, Finding("info", f"on {d.name}"))
            _record(run, "reference", attempt, g)
            failed |= g.status == "fail"
        if not failed:
            return candidate
        if not fix or attempt == RETRIES:
            return False
        # The judge sends the failure back to the reference; an authoring agent fixes it in a sandbox.
        res = fix_reference(pack, train, docker.image(pack, "ref"), attempt, model=fix_model, start=candidate)
        run.log.append({"stage": "fix-reference", "attempt": attempt, "status": "fail" if res["error"] else "info",
                        "send_back": "pack" if res["disputed"] else None,
                        "findings": [{"level": "info", "text": res["summary"][:1500]}] +
                                    ([{"level": "warn", "text": "DISPUTE: " + res["dispute"][:1500]}] if res["disputed"] else []),
                        "cost_usd": res["cost_usd"]})
        if res["disputed"] or res["error"]:
            return False
        candidate = train[0] / f"candidate-{len(train)}-{attempt}.py"
        shutil.copy(res["fixed_file"], candidate)
    return False


HOLDOUT_OFFSET = 1000
HOLDOUT_ROUNDS = 3   # a failed holdout becomes training data, and the next round draws a fresh seed


def _holdout(run: BuildRun, pack: Domain, out: Path, candidate: Path, rnd: int = 1) -> Path | None:
    """A fixed reference must also pass on a seed the fixing agent never saw. Returns None when it passes,
    else the holdout's build directory (holding reference.json when the reference ran)."""
    import shutil

    from . import docker
    from .gates import Finding, reference_gate, render_gate

    seed = run.seed + HOLDOUT_OFFSET * rnd
    hold = out / f"holdout-{seed}"
    if hold.exists():
        shutil.rmtree(hold)
    plan = make_plan(pack, seed)
    corpus = make_corpus(pack, plan, seed)
    _write(hold, pack, plan, corpus, BuildRun(pack.name, seed))
    try:
        docker.render(pack, hold)
        g = render_gate(hold)
        if g.status == "fail":
            g.gate = "holdout-render"
            _record(run, "holdout", rnd, g)
            return hold
        docker.reference(pack, hold, solution=candidate)
    except Exception as e:  # any failure to check is a failed check
        (hold / "reference.json").unlink(missing_ok=True)
        run.log.append({"stage": "holdout", "attempt": rnd, "status": "fail", "send_back": None,
                        "findings": [{"level": "fail", "text": f"holdout could not run: {e}"}]})
        return hold
    g = reference_gate(hold)
    g.gate = "holdout"
    g.findings.insert(0, Finding("info", f"seed {seed}"))
    _record(run, "holdout", rnd, g)
    return None if g.status != "fail" else hold

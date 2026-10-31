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
          task_dir: Path | None = None, fix: bool = False) -> BuildRun:
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
            _docker_stages(run, pack, Path(out), task_dir, fix)
        return run
    run.verdict = "stopped"
    return run


def _docker_stages(run: BuildRun, pack: Domain, out: Path, task_dir: Path | None, fix: bool = False) -> None:
    import shutil

    from . import docker
    from .agent import fix_reference
    from .assemble import assemble
    from .gates import reference_gate, render_gate

    docker.render(pack, out)
    g = render_gate(out)
    _record(run, "render", 0, g)
    if g.status == "fail":
        run.verdict, run.stopped_at = "stopped", "render"
        return
    ref_file = pack.root / "task" / "solution" / "intake.py"
    original = ref_file.read_text()
    fixed = False
    for attempt in range(RETRIES + 1):
        docker.reference(pack, out)
        g = reference_gate(out)
        _record(run, "reference", attempt, g)
        if g.status != "fail":
            break
        if not fix or attempt == RETRIES:
            run.verdict, run.stopped_at = "stopped", "reference"
            return
        # The judge sends the failure back to the reference; an authoring agent fixes it in a sandbox.
        res = fix_reference(pack, out, docker.image(pack, "ref"), attempt)
        run.log.append({"stage": "fix-reference", "attempt": attempt, "status": "fail" if res["error"] else "info",
                        "send_back": "pack" if res["disputed"] else None,
                        "findings": [{"level": "info", "text": res["summary"][:1500]}] +
                                    ([{"level": "warn", "text": "DISPUTE: " + res["dispute"][:1500]}] if res["disputed"] else []),
                        "cost_usd": res["cost_usd"]})
        if res["disputed"] or res["error"]:
            run.verdict, run.stopped_at = "stopped", "reference"
            return
        shutil.copy(res["fixed_file"], ref_file)
        fixed = True
    if fixed and not _holdout(run, pack, out):
        ref_file.write_text(original)
        run.verdict, run.stopped_at = "stopped", "holdout"
        return
    name = f"{pack.name}-s{run.seed}"
    assemble(pack, out, task_dir or out / "task" / name, name)
    run.verdict = "task assembled, ready for trials"
    (out / "build.json").write_text(json.dumps({"verdict": run.verdict, "log": run.log}, indent=1))


HOLDOUT_OFFSET = 1000


def _holdout(run: BuildRun, pack: Domain, out: Path) -> bool:
    """A fixed reference must also pass on a seed the fixing agent never saw."""
    from . import docker
    from .gates import reference_gate

    seed = run.seed + HOLDOUT_OFFSET
    hold = out / f"holdout-{seed}"
    plan = make_plan(pack, seed)
    corpus = make_corpus(pack, plan, seed)
    _write(hold, pack, plan, corpus, BuildRun(pack.name, seed))
    docker.render(pack, hold)
    docker.reference(pack, hold)
    g = reference_gate(hold)
    g.gate = "holdout"
    _record(run, "holdout", 0, g)
    return g.status != "fail"

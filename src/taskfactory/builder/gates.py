"""Build-time gates: checked on the pack, the plan and the corpus before anything is rendered or run.

They return the same GateResult as the evidence gates. A failure names where the task goes back to: the pack
(rules or features need a person or an authoring agent) or the plan (a new composition can fix it).
"""
from __future__ import annotations

import random
from collections import Counter

from ..gates import Finding, GateResult, _result
from .corpus import Corpus, make_corpus
from .pack import Domain
from .plan import ItemPlan, Plan, buildable, make_plan

MIN_STYLES = 3


def pack_gate(pack: Domain) -> GateResult:
    f: list[Finding] = []
    ids = [r.id for r in pack.rules]
    if len(ids) != len(set(ids)):
        f.append(Finding("fail", "rule ids repeat"))
    known = set(ids)
    exercised = {r for x in pack.features for r in x.rules} | {r for rs in pack.route_rules.values() for r in rs}
    for x in pack.features:
        bad = [r for r in x.rules if r not in known]
        if bad:
            f.append(Finding("fail", f"feature '{x.name}' cites rules {bad} the pack does not state"))
        for other in x.requires_any + x.excludes:
            if other not in {y.name for y in pack.features}:
                f.append(Finding("fail", f"feature '{x.name}' names unknown feature '{other}'"))
    for r in pack.rules:
        if r.id not in exercised:
            f.append(Finding("fail", f"rule {r.id} ({r.title}) is written but no feature or route exercises it"))
        if not r.mutant:
            f.append(Finding("warn", f"rule {r.id} ({r.title}) has no mutant: failures on it can only be attributed by a judge"))
    rng = random.Random("pack-gate")
    for x in pack.features:
        ok = False
        for i in range(40):
            feats = {x.name}
            if x.requires_any:
                feats.add(rng.choice(x.requires_any))
            route = rng.choice(x.routes)
            it = ItemPlan(f"probe{i}", rng.choice(pack.styles), route, 1, frozenset(feats))
            if buildable(pack, it, 0):
                ok = True
                break
        if not ok:
            f.append(Finding("fail", f"feature '{x.name}' could not be built on any route or style tried"))
    if not any(x.level == "fail" for x in f):
        f.append(Finding("info", f"{len(pack.rules)} rules, {len(pack.features)} features, every feature buildable"))
    return _result("pack", "Pack: are the rules and features complete and buildable?", f, "pack")


def spec_gate(pack: Domain, plan: Plan) -> GateResult:
    f: list[Finding] = []
    shown = Counter(x for it in plan.samples for x in it.features)
    for x in pack.features:
        if not shown[x.name]:
            f.append(Finding("fail", f"no worked sample shows '{x.name}' (rules {', '.join(map(str, x.rules))}); agents would meet it first on hidden items"))
    several = {it.style for it in plan.samples if it.units > 1}
    if pack.units_max > 1:
        for st in pack.styles:
            if st not in several:
                f.append(Finding("fail", f"no worked sample shows style '{st}' with several units; "
                                         "each style lays them out its own way"))
    routes = {it.route for it in plan.samples}
    for r in pack.routes:
        if r not in routes:
            f.append(Finding("warn", f"no worked sample comes by route '{r}'"))
    if len(plan.samples) > pack.samples_max:
        f.append(Finding("fail", f"{len(plan.samples)} samples, more than the {pack.samples_max} allowed"))
    if not any(x.level == "fail" for x in f):
        f.append(Finding("info", f"{len(plan.samples)} samples show all {len(pack.features)} features and {len(routes)} of {len(pack.routes)} routes"))
    return _result("spec", "Spec: does every rule have a worked example?", f, "plan")


def corpus_gate(pack: Domain, plan: Plan, corpus: Corpus, seed: int) -> GateResult:
    f: list[Finding] = []
    send = "plan"
    again = make_corpus(pack, plan, seed)
    if again.digest() != corpus.digest():
        f.append(Finding("fail", "the same seed gave a different corpus"))
        send = "pack"
    else:
        f.append(Finding("info", "same seed, same corpus"))
    other = make_plan(pack, seed + 1)
    key = lambda p: [(i.style, i.route, i.units, tuple(sorted(i.features))) for i in p.hidden]
    if key(other) == key(plan):
        f.append(Finding("fail", "the next seed draws the same composition"))
    styles = {i.style for i in plan.hidden}
    if len(styles) < MIN_STYLES:
        f.append(Finding("fail", f"hidden items use {len(styles)} styles; at least {MIN_STYLES} keep the generator from being fingerprinted"))
    missing_routes = set(pack.routes) - {i.route for i in plan.hidden}
    if missing_routes:
        f.append(Finding("warn", f"no hidden item comes by {', '.join(sorted(missing_routes))}"))
    in_hidden = Counter(x for i in plan.hidden for x in i.features)
    for x in pack.features:
        if not in_hidden[x.name]:
            f.append(Finding("fail", f"no hidden item has '{x.name}'"))
    sample_ids = {i.id for i in plan.samples}
    hidden_ids = {i.id for i in plan.hidden}
    for r in pack.rules:
        if not r.mutant:
            continue
        h = [i for i in hidden_ids if r.id in corpus.mutants.get(i, {})]
        s = [i for i in sample_ids if r.id in corpus.mutants.get(i, {})]
        if not h:
            f.append(Finding("fail", f"rule {r.id} ({r.title}) decides no hidden item: an agent could ignore it and lose nothing"))
        elif not s:
            f.append(Finding("fail", f"rule {r.id} ({r.title}) decides {len(h)} hidden items but no worked sample"))
        else:
            f.append(Finding("info", f"rule {r.id} ({r.title}) decides {len(h)} hidden items and {len(s)} samples"))
    return _result("corpus", "Corpus: deterministic, varied, and every rule tested?", f, send)


def render_gate(build_dir) -> GateResult:
    """Every item drawn, and drawing changed no answer."""
    import json
    from pathlib import Path

    f: list[Finding] = []
    p = Path(build_dir) / "render.json"
    if not p.exists():
        return _result("render", "Render: is every item drawn, with its answer unchanged?", [Finding("fail", "nothing rendered yet")], "pack")
    rs = json.loads(p.read_text())
    for r in rs:
        if r.get("error"):
            f.append(Finding("fail", f"{r['id']} did not render: {r['error']}"))
        elif not r.get("truth_unchanged"):
            f.append(Finding("fail", f"{r['id']}: drawing changed its answer; truth must come from the model alone"))
    if not f:
        f.append(Finding("info", f"{len(rs)} items drawn; every answer unchanged by drawing"))
    return _result("render", "Render: is every item drawn, with its answer unchanged?", f, "pack")


def reference_gate(build_dir, limit: float = 120.0, headroom: float = 0.5) -> GateResult:
    """The reference gets every item right, with time to spare: proof the task can be done."""
    import json
    from pathlib import Path

    f: list[Finding] = []
    p = Path(build_dir) / "reference.json"
    if not p.exists():
        return _result("reference", "Reference: can the task be done?", [Finding("fail", "reference not run yet")], "reference")
    rs = json.loads(p.read_text())
    m = Path(build_dir) / "manifest.json"
    if m.exists():
        mm = json.loads(m.read_text())
        planned = {i["id"] for i in mm["samples"] + mm["hidden"]}
        missing = sorted(planned - {r["id"] for r in rs})
        if missing or not rs:
            f.append(Finding("fail", f"reference has no result for {', '.join(missing) or 'any item'}"))
    elif not rs:
        f.append(Finding("fail", "reference produced no results"))
    wrong = [r for r in rs if not r["ok"]]
    for r in wrong:
        f.append(Finding("fail", f"{r['id']}: " + "; ".join(r["diffs"][:3])))
    timed = [r for r in rs if "seconds_parallel" in r] or rs
    slow = max((r["seconds"] for r in timed), default=0)
    if slow > limit * headroom:
        f.append(Finding("warn", f"slowest item took {slow:.0f} s of the {limit:.0f} s limit"))
    if not wrong and not f:
        f.append(Finding("info", f"reference right on all {len(rs)} items; slowest {slow:.0f} s alone, against a {limit:.0f} s limit"))
    return _result("reference", "Reference: can the task be done?", f, "reference")

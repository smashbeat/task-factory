"""The composition of a corpus, drawn per seed.

Samples are chosen first, greedily, until every feature appears in at least one worked sample, every style is
shown with several units, and as many routes as fit. Hidden items then combine features, favouring the least used features, routes and styles, so
each seed gives a different mix. Every item is built once here to prove the pack can make it.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .pack import Domain


@dataclass(frozen=True)
class ItemPlan:
    id: str
    style: str
    route: str
    units: int
    features: frozenset[str]


@dataclass
class Plan:
    seed: int
    attempt: int
    samples: list[ItemPlan]
    hidden: list[ItemPlan]
    uncovered: set[str] = field(default_factory=set)


def _consistent(pack: Domain, feats: set[str], route: str, units: int) -> bool:
    for name in feats:
        f = pack.feature(name)
        if route not in f.routes or units > f.units or set(f.excludes) & feats:
            return False
        if f.requires_any and not set(f.requires_any) & feats:
            return False
    return True


def _close(pack: Domain, feats: set[str], rng: random.Random) -> set[str]:
    """Add a partner for every feature that needs one."""
    feats = set(feats)
    for _ in range(4):
        for name in sorted(feats):
            f = pack.feature(name)
            if f.requires_any and not set(f.requires_any) & feats:
                feats.add(rng.choice(f.requires_any))
    return feats


def buildable(pack: Domain, it: ItemPlan, seed: int) -> bool:
    if not pack.module.valid(it.style, it.route, it.units, it.features):
        return False
    try:
        model = pack.module.build(it.id, it.style, it.route, it.units, it.features, random.Random(f"{seed}-{it.id}"))
        pack.module.truth(model)
        return True
    except Exception:
        return False


def decided_rules(pack: Domain, it: ItemPlan, seed: int) -> set[int]:
    """The rules whose mutant answer differs from the truth on this item."""
    model = pack.module.build(it.id, it.style, it.route, it.units, it.features, random.Random(f"{seed}-{it.id}"))
    t = pack.module.truth(model)
    return {r.id for r in pack.rules if r.mutant and pack.module.truth(model, frozenset({r.id})) != t}


def _candidate(pack, rng, want: list[str], routes_w, styles_w, item_id, seed, k_extra):
    feats = _close(pack, set(want), rng)
    pool = [f.name for f in pack.features if f.name not in feats]
    rng.shuffle(pool)
    for name in pool[:k_extra]:
        trial = _close(pack, feats | {name}, rng)
        if any(set(pack.feature(n).excludes) & trial for n in trial):
            continue
        feats = trial
    routes = [r for r in pack.routes if all(r in pack.feature(n).routes for n in feats)]
    if not routes:
        return None
    route = rng.choices(routes, weights=[routes_w(r) for r in routes])[0]
    cap = min([pack.units_max] + [pack.feature(n).units for n in feats])
    units = rng.randint(1, cap)
    style = rng.choices(pack.styles, weights=[styles_w(s) for s in pack.styles])[0]
    it = ItemPlan(item_id, style, route, units, frozenset(feats))
    if not _consistent(pack, set(feats), route, units) or not buildable(pack, it, seed):
        return None
    return it


def make_plan(pack: Domain, seed: int, attempt: int = 0) -> Plan:
    rng = random.Random(f"plan-{seed}-{attempt}")
    names = [f.name for f in pack.features]

    samples: list[ItemPlan] = []
    uncovered = set(names)
    routes_left = set(pack.routes)
    style_use: Counter = Counter()
    rules_left = {r.id for r in pack.rules if r.mutant}
    several_left = set(pack.styles) if pack.units_max > 1 else set()   # styles not yet shown with several units
    while (uncovered or routes_left or rules_left or several_left) and len(samples) < pack.samples_max:
        sid = f"s{len(samples) + 1:02d}"
        best, best_score = None, 0.0
        for _ in range(120):
            pool = sorted(uncovered) or names
            want = rng.sample(pool, k=min(len(pool), rng.randint(1, 3) if uncovered else 1))
            it = _candidate(
                pack, rng, want,
                routes_w=lambda r: (50.0 if not uncovered else 4.0) if r in routes_left else 1.0,
                styles_w=lambda s: (4.0 if s in several_left else 1.0) / (1 + style_use[s]),
                item_id=sid, seed=seed, k_extra=0,
            )
            if it is None:
                continue
            rules = decided_rules(pack, it, seed)
            score = (len(it.features & uncovered) + 0.5 * (it.route in routes_left) + 1.5 * len(rules & rules_left)
                     + 1.0 * (it.units > 1 and it.style in several_left))
            if score > best_score:
                best, best_score, best_rules = it, score, rules
        if best is None:
            break
        rules_left -= best_rules
        samples.append(best)
        uncovered -= best.features
        routes_left.discard(best.route)
        if best.units > 1:
            several_left.discard(best.style)
        style_use[best.style] += 1

    hidden: list[ItemPlan] = []
    f_use: Counter = Counter()
    r_use: Counter = Counter()
    s_use: Counter = Counter()
    rule_use: Counter = Counter()
    target = pack.hidden / max(1, sum(r.mutant for r in pack.rules))
    for n in range(pack.hidden):
        hid = f"h{n + 1:02d}"
        best, best_score = None, -1.0
        for _ in range(40):
            least = sorted(names, key=lambda x: (f_use[x], rng.random()))
            want = [least[0]] if rng.random() < 0.7 else [rng.choice(names)]
            it = _candidate(
                pack, rng, want,
                routes_w=lambda r: 12.0 if not r_use[r] else 1.0 / (1 + r_use[r]),
                styles_w=lambda s: 1.0 / (1 + s_use[s]),
                item_id=hid, seed=seed, k_extra=rng.randint(0, 2),
            )
            if it is None:
                continue
            rules = decided_rules(pack, it, seed)
            score = (sum(1.0 / (1 + f_use[x]) for x in it.features) + (3.0 if not r_use[it.route] else 1.0 / (1 + r_use[it.route]))
                     + 3.0 * sum(1.0 / (1 + rule_use[r]) ** 2 for r in rules)
                     - 2.0 * sum(max(0.0, rule_use[r] + 1 - target) for r in rules))
            if score > best_score:
                best, best_score, best_rules = it, score, rules
        if best is None:
            continue
        rule_use.update(best_rules)
        hidden.append(best)
        f_use.update(best.features)
        r_use[best.route] += 1
        s_use[best.style] += 1
    return Plan(seed, attempt, samples, hidden, uncovered)

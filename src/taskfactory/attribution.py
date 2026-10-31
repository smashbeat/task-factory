"""Why did an agent fail an item: a rule it was given, or the page?

Cheapest evidence first. The generator knows which features it put on each item, and the task profile says
what each feature looks like when an agent breaks the rule behind it (a signature). A diff that matches a
signature is rule-decided. A diff the page could explain (a scanned route, an overlay, a value that is the
right text with extra or garbled characters) is a reading miss. Whatever is left is unexplained, and only
that residue needs a model or a person to judge.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .diffs import Diff
from .evidence import Item, Pack, Trial


@dataclass(frozen=True)
class Signature:
    symptom: str  # lot_count_over, row_count_over, field, contains, decision_only
    rules: tuple[int, ...]
    says: str
    feature: str | None = None
    field: str | None = None
    fields: tuple[str, ...] = ()
    contains: str | None = None


@dataclass(frozen=True)
class Profile:
    name: str
    manifest: str
    policy: str
    decision_fields: frozenset[str]
    reading_routes: frozenset[str]
    reading_features: frozenset[str]
    signatures: tuple[Signature, ...]


@dataclass
class Attribution:
    item: str
    kind: str  # rule, reading, unexplained
    rules: tuple[int, ...] = ()
    says: str = ""
    features: tuple[str, ...] = ()
    evidence: list[Diff] = field(default_factory=list)
    residue: list[Diff] = field(default_factory=list)


def load_profile(path: Path) -> Profile:
    d = tomllib.loads(Path(path).read_text())
    t = d["task"]
    sigs = tuple(
        Signature(
            symptom=s["symptom"],
            rules=tuple(s["rules"]),
            says=s["says"],
            feature=s.get("feature"),
            field=s.get("field"),
            fields=tuple(s.get("fields", ())),
            contains=s.get("contains"),
        )
        for s in d.get("signature", [])
    )
    return Profile(
        name=t["name"],
        manifest=t.get("manifest", "manifest.json"),
        policy=t.get("policy", "policy.md"),
        decision_fields=frozenset(t.get("decision_fields", ())),
        reading_routes=frozenset(t.get("reading_routes", ())),
        reading_features=frozenset(t.get("reading_features", ())),
        signatures=sigs,
    )


def _decision_only(diffs: list[Diff], lot: int | None, decision: frozenset[str]) -> bool:
    """The lot's decision is wrong while every value on it was read right."""
    if any(d.kind in ("lot_count", "other") for d in diffs):
        return False
    on_lot = [d for d in diffs if d.lot == lot]
    return bool(on_lot) and all(d.kind == "field" and d.field in decision for d in on_lot)


def _matches(sig: Signature, d: Diff, diffs: list[Diff], p: Profile) -> bool:
    if sig.symptom == "lot_count_over":
        return d.kind == "lot_count" and d.got > d.want
    if sig.symptom == "row_count_over":
        return d.kind == "row_count" and d.got > d.want
    if sig.symptom == "field":
        return d.kind == "field" and d.field == sig.field
    if sig.symptom == "contains":
        return (
            d.kind == "field"
            and d.field in sig.fields
            and isinstance(d.got, str)
            and sig.contains in d.got
            and sig.contains not in str(d.want)
        )
    if sig.symptom == "decision_only":
        return d.kind == "field" and d.field in p.decision_fields and _decision_only(diffs, d.lot, p.decision_fields)
    return False


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _subsequence(small: list[str], big: list[str]) -> bool:
    it = iter(big)
    return all(any(w == x for x in it) for w in small)


def _looks_misread(got: object, want: object) -> bool:
    """The right text with characters garbled, added or dropped: what a misread looks like."""
    if not (isinstance(got, str) and isinstance(want, str)):
        return False
    g, w = got.casefold(), want.casefold()
    if _edit_distance(g, w) <= max(2, len(w) // 5):
        return True
    return _subsequence(w.split(), g.split()) or _subsequence(g.split(), w.split())


def _reading(d: Diff, item: Item, diffs: list[Diff], p: Profile) -> bool:
    on_page = item.route in p.reading_routes
    if d.kind in ("lot_count", "row_count"):
        return on_page or bool(p.reading_features & set(item.features))
    if d.kind != "field":
        return False
    miscounted = any(
        x.kind == "row_count" and x.lot == d.lot and _reading(x, item, diffs, p) for x in diffs
    )
    if d.row is not None and miscounted:
        # Once a row is merged or split, every row on that lot is compared with its neighbour's truth.
        return True
    if d.field in p.decision_fields:
        # A wrong decision on a lot that also has a misread value follows from the misread.
        return any(x.kind != "field" or x.field not in p.decision_fields for x in diffs if x.lot == d.lot)
    return on_page or _looks_misread(d.got, d.want)


def attribute_item(item: Item, diffs: list[Diff], p: Profile) -> Attribution:
    rule_hits: list[tuple[Signature, Diff]] = []
    explained: set[int] = set()
    for i, d in enumerate(diffs):
        for sig in p.signatures:
            if sig.feature is not None and sig.feature not in item.features:
                continue
            if _matches(sig, d, diffs, p):
                rule_hits.append((sig, d))
                explained.add(i)
                break
    residue = [d for i, d in enumerate(diffs) if i not in explained and not _reading(d, item, diffs, p)]
    if rule_hits:
        sig = rule_hits[0][0]
        rules = tuple(sorted({r for s, _ in rule_hits for r in s.rules}))
        says = "; ".join(dict.fromkeys(s.says for s, _ in rule_hits))
        feats = tuple(dict.fromkeys(s.feature for s, _ in rule_hits if s.feature))
        return Attribution(item.id, "rule", rules, says, feats, [d for _, d in rule_hits], residue)
    if residue:
        return Attribution(item.id, "unexplained", evidence=list(diffs), residue=residue)
    return Attribution(item.id, "reading", says="misread what prints", evidence=list(diffs))


def attribute_trial(trial: Trial, pack: Pack, p: Profile) -> list[Attribution]:
    return [attribute_item(pack.items[i], diffs, p) for i, diffs in sorted(trial.failed.items())]

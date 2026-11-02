"""The size-set model: numbers, the spec in force, the truth and its mutants, and the builder gates on it."""
import importlib.util
import random
import sys
from fractions import Fraction as F
from pathlib import Path

import pytest

from taskfactory.builder.corpus import make_corpus
from taskfactory.builder.gates import corpus_gate, pack_gate, spec_gate
from taskfactory.builder.pack import load_domain
from taskfactory.builder.plan import make_plan

ROOT = Path(__file__).parent.parent
PACK = ROOT / "packs" / "size-set"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"size_set_{name}", PACK / f"{name}.py")
    sys.path.insert(0, str(PACK))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"size_set_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


model = _load("model")


@pytest.fixture(scope="module")
def pack():
    return load_domain(PACK)


def build(features, style="plm", route="digital", units=3, key="t"):
    c = model.Report("t", style, random.Random(f"{key}-{'-'.join(sorted(features))}"), units, set(features), route)
    model.apply_features(c)
    return c


# ------------------------------------------------------------------ numbers

@pytest.mark.parametrize("text,value", [
    ("20 1/4", F(81, 4)), ("20-1/4", F(81, 4)), ("20¼", F(81, 4)), ("20.25", F(81, 4)), ("⅛", F(1, 8)),
    ("-1 1/8", F(-9, 8)), ("+3/8", F(3, 8)), ("51.4", F(257, 5)), ("0", F(0)), ("81/4", F(81, 4)),
])
def test_every_notation_parses_to_the_same_number(text, value):
    assert model.parse_qty(text) == value


def test_formatting_round_trips_and_uses_lowest_terms():
    assert model.fmt_qty(F(81, 4), "in") == "20 1/4"
    assert model.fmt_qty(F(161, 8), "in", notation="dash") == "20-1/8"
    assert model.fmt_qty(F(81, 4), "in", notation="glyph") == "20¼"
    assert model.fmt_qty(F(81, 4), "in", notation="decimal") == "20.25"
    assert model.fmt_qty(F(-9, 8), "in", signed=True) == "-1 1/8"
    assert model.fmt_qty(F(0), "in", signed=True) == "0"
    assert model.fmt_qty(F(257, 5), "cm") == "51.4"
    assert model.fmt_qty(F(1, 2), "cm", signed=True) == "+0.5"


def test_rounding_goes_to_the_nearest_step_with_halves_up():
    assert model.round_to(F(161, 16), F(1, 8)) == F(81, 8)      # exactly halfway: up
    assert model.round_to(F(159, 16), F(1, 8)) == F(80, 8)      # halfway below the step: up to it
    assert model.round_to(F(2027, 100), F(1, 8)) == F(81, 4)    # 20.27 -> 20 1/4
    assert model.round_to(F(5143, 100), F(1, 10)) == F(514, 10)


def test_an_inch_is_exactly_two_point_five_four_centimetres():
    assert model.convert(F(20), "in", "cm") == F(508, 10)
    assert model.convert(F(508, 10), "cm", "in") == F(20)


# ------------------------------------------------------------------ the spec in force

def test_grading_and_revisions_give_the_spec_in_force():
    import datetime as dt
    spec = {"sizes": ["S", "M", "L", "XL"], "base_size": "M", "revisions": [
        {"rev": 2, "date": "2026-08-01", "code": "102", "sizes": ["L", "XL"], "set": "22"},
        {"rev": 3, "date": "2026-08-20", "code": "102", "sizes": "all", "change": "-1/2"},
        {"rev": 4, "date": "2026-10-01", "code": "102", "sizes": "all", "change": "+5"},
    ], "points": [{"code": "102", "base": "20", "grade": {"M": "+1", "L": "+1", "XL": "+1 1/2"}}]}
    force = model.spec_in_force(spec, dt.date(2026, 9, 10))
    assert force == {("102", "S"): F(19) - F(1, 2), ("102", "M"): F(20) - F(1, 2), ("102", "L"): F(22) - F(1, 2),
                     ("102", "XL"): F(22) - F(1, 2)}
    base = model.spec_in_force(spec, dt.date(2026, 9, 10), off={4})
    assert set(base.values()) == {F(20)}


# ------------------------------------------------------------------ the truth

def test_a_plain_report_is_approved_with_every_row_within():
    t = build(set()).truth()
    assert t["decision"] == "approved"
    assert all(r["within"] is True for r in t["measurements"])
    assert all(r["piece"] == 1 for r in t["measurements"])


def test_rows_follow_spec_order_then_size_then_piece():
    c = build({"size_order", "two_pieces"}, units=4)
    rows = c.truth()["measurements"]
    codes = [p["code"] for p in c.spec_points]
    keys = [(codes.index(r["code"]), c.sizes.index(r["size"]), r["piece"]) for r in rows]
    assert keys == sorted(keys)
    assert c.sizes_measured != c.sizes
    assert any(r["piece"] == 2 for r in rows)


def test_an_unmeasured_size_gets_null_rows_and_the_report_is_incomplete():
    c = build({"size_missing"}, units=3)
    t = c.truth()
    gone = (set(c.sizes) - set(c.sizes_measured)).pop()
    rows = [r for r in t["measurements"] if r["size"] == gone]
    assert rows and all(r["measured"] is None and r["within"] is None and r["piece"] == 1 for r in rows)
    assert t["decision"] == "incomplete"


@pytest.mark.parametrize("feature,decision", [
    ("critical_out", "rejected"), ("many_out", "rejected"), ("comments_only", "approved_with_comments"),
    ("pom_missing", "incomplete"), ("tol_edge", "approved"),
])
def test_the_decision_ladder(feature, decision):
    assert build({feature}).truth()["decision"] == decision


def test_a_full_circumference_is_halved_before_comparing():
    c = build({"full_circ"})
    code = next(iter(c.full_circ))
    key = next(k for k in c.printed if k[0] == code)
    assert c.printed[key] == 2 * c.true[key]
    rows = {(r["code"], r["size"], r["piece"]): r for r in c.truth()["measurements"]}
    assert model.parse_qty(rows[key]["measured"]) == c.true[key]
    assert rows[key]["within"] is True
    assert rows[key]["within"] is True and c.truth(off={6})["measurements"] != c.truth()["measurements"]


@pytest.mark.parametrize("printed", ["cm_report", "in_report", "fine_print", "decimal_inches"])
def test_rounding_traps_sit_on_the_half_step(printed):
    c = build({"round_edge", "round_fail", printed}, key="r")
    force = c.in_force()
    rows = {(r["code"], r["size"], r["piece"]): r for r in c.truth()["measurements"]}
    edge = fail = False
    for key, v in c.printed.items():
        if v is None:
            continue
        p = c.point(key[0])
        raw = model.convert(v, c.printed_unit, c.unit) / (2 if key[0] in c.full_circ else 1)
        lower, upper = force[key[:2]] - p["tol_minus"], force[key[:2]] + p["tol_plus"]
        if raw < lower and rows[key]["within"] is True:
            edge = True                 # under the bound unrounded, on it after rounding
        if upper < raw < upper + c.prec and rows[key]["within"] is False:
            fail = True                 # over the bound by less than a step, rounded off it
    assert edge and fail


def test_the_latest_re_measurement_wins_and_a_correction_changes_the_print():
    c = build({"remeasure_block", "remeasure_twice", "stamp_value"}, key="m")
    rows = {(r["code"], r["size"], r["piece"]): r for r in c.truth()["measurements"]}
    first, second = c.remeasurements
    assert second["date"] > first["date"]
    key = next(iter(second["values"]))
    assert model.parse_qty(rows[key]["measured"]) == c.house_value(key, second["values"][key], second["unit"])
    skey = next(iter(c.corrections))
    assert model.parse_qty(rows[skey]["measured"]) == c.house_value(skey, c.corrections[skey]["right"], c.printed_unit)
    assert c.corrections[skey]["wrong"] != c.corrections[skey]["right"]


def test_a_late_revision_does_not_apply():
    c = build({"rev_late"})
    r = c.late_revision
    assert r["date"] > c.measured_on
    assert c.in_force() == model.spec_in_force({**c.spec, "revisions": c.spec["revisions"][:-1]}, c.measured_on)


def test_each_switch_changes_some_answer(pack):
    changed = set()
    for f in pack.features:
        for style in pack.styles:
            feats = {f.name}
            if f.requires_any:
                feats.add(f.requires_any[0])
            units = max(pack.feature(n).units_min for n in feats)
            if not pack.module.valid(style, "digital", units, frozenset(feats)):
                continue
            c = pack.module.build("x", style, "digital", units, frozenset(feats), random.Random(f"7-{f.name}-{style}"))
            base = c.truth()
            for r in (3, 4, 5, 6, 7, 8, 9, 10):
                if c.truth(frozenset({r})) != base:
                    changed.add(r)
    assert changed == {3, 4, 5, 6, 7, 8, 9, 10}


# ------------------------------------------------------------------ the builder on the pack

@pytest.fixture(scope="module")
def plan(pack):
    return make_plan(pack, seed=1)


def test_gates_pass_on_seed_one(pack, plan):
    corpus = make_corpus(pack, plan, seed=1)
    assert pack_gate(pack).status != "fail"
    g = spec_gate(pack, plan)
    assert g.status != "fail", [x.text for x in g.findings]
    g = corpus_gate(pack, plan, corpus, seed=1)
    assert g.status != "fail", [x.text for x in g.findings]
    assert len(plan.hidden) == pack.hidden

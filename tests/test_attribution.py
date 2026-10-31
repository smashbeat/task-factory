from pathlib import Path

from taskfactory.attribution import attribute_trial, load_profile
from taskfactory.evidence import load_pack

PACK = Path(__file__).parent / "fixtures" / "coa-intake"

# The hand-made failure table in coa-intake's docs/failure-analysis.md.
HAND_RULE_DECIDED = {
    "AJojEBX": {"h01", "h03", "h10", "h29"},
    "JjKSvue": {"h11"},
    "xYcSLSa": {"h01", "h11"},
    "HoDVDHy": {"h12", "h27"},
    "qLxSTzB": {"h03", "h10", "h15", "h27"},
    "ry4jAKd": {"h03", "h10", "h15", "h27", "h30"},
}


def _attributions():
    pack = load_pack(PACK)
    profile = load_profile(PACK / "factory.toml")
    return {t.name.split("__")[-1]: attribute_trial(t, pack, profile) for t in pack.trials if t.kind == "standard"}


def test_reproduces_the_hand_made_failure_table():
    for trial, items in _attributions().items():
        got = {a.item for a in items if a.kind == "rule"}
        assert got == HAND_RULE_DECIDED[trial], trial


def test_every_other_failure_is_a_reading_miss():
    for trial, items in _attributions().items():
        others = {a.item: a.kind for a in items if a.kind != "rule"}
        assert set(others.values()) <= {"reading"}, (trial, others)


def test_rules_and_reasons_are_carried():
    items = {a.item: a for a in _attributions()["JjKSvue"]}
    assert items["h11"].rules == (4, 6)
    assert "footnote" in items["h11"].says
    items = {a.item: a for a in _attributions()["AJojEBX"]}
    assert items["h29"].rules == (5, 8)
    assert items["h01"].rules == (1, 9)

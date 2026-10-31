import copy
from pathlib import Path

from taskfactory.attribution import load_profile
from taskfactory.evidence import load_pack
from taskfactory.gates import cheat, difficulty, fairness, quality
from taskfactory.pipeline import run

PACK = Path(__file__).parent / "fixtures" / "coa-intake"


def _pack():
    return load_pack(PACK)


def _profile():
    return load_profile(PACK / "factory.toml")


def test_quality_passes_on_coa_intake():
    r = quality(_pack(), _profile())
    assert r.status == "pass", r.findings


def test_quality_sends_a_failing_oracle_back_to_the_verifier():
    pack = _pack()
    next(t for t in pack.trials if t.kind == "oracle").reward = 0
    r = quality(pack, _profile())
    assert r.status == "fail" and r.send_back == "verifier"


def test_difficulty_passes_but_warns_about_a_thin_margin():
    r = difficulty(_pack(), _profile())
    assert r.status == "warn"
    assert any("28 of 30" in f.text for f in r.findings)


def test_difficulty_sends_a_solved_task_back_to_design():
    pack = _pack()
    pack.trial("JjKSvue").reward = 1
    r = difficulty(pack, _profile())
    assert r.status == "fail" and r.send_back == "design"


def test_difficulty_wants_two_families():
    pack = _pack()
    pack.trials = [t for t in pack.trials if t.agent != "codex"]
    r = difficulty(pack, _profile())
    assert any("one agent family" in f.text for f in r.findings)


def test_fairness_passes_and_flags_rules_without_a_worked_sample():
    r = fairness(_pack(), _profile())
    assert r.status == "warn"
    unshown = [f.text for f in r.findings if "no sample shows" in f.text]
    assert any("stamp_retest" in t for t in unshown)
    assert not any("'continuation'" in t for t in unshown)


def test_fairness_sends_back_a_trial_that_failed_only_on_reading():
    pack = _pack()
    t = pack.trial("JjKSvue")
    t.failed = {"h19": t.failed["h19"]}
    r = fairness(pack, _profile())
    assert r.status == "fail" and r.send_back == "design"
    assert any("JjKSvue" in f.text for f in r.findings)


def test_fairness_flags_an_item_no_trial_solved():
    pack = _pack()
    for t in pack.trials:
        if t.kind == "standard":
            t.failed.setdefault("h02", [])
    r = fairness(pack, _profile())
    assert any("h02" in f.text and "no trial" in f.text for f in r.findings)


def test_cheat_passes_and_fails():
    assert cheat(_pack(), _profile()).status == "pass"
    pack = _pack()
    next(t for t in pack.trials if t.kind == "cheat").reward = 1
    r = cheat(pack, _profile())
    assert r.status == "fail" and r.send_back == "environment"


def test_pipeline_stops_at_the_first_failure():
    pack = _pack()
    next(t for t in pack.trials if t.kind == "oracle").reward = 0
    out = run(pack, _profile())
    assert [g.gate for g in out.gates] == ["quality"]
    assert out.verdict == "send back" and out.send_back == "verifier"
    assert out.skipped == ["difficulty", "fairness", "cheat"]


def test_pipeline_on_coa_intake_ships_with_warnings():
    out = run(_pack(), _profile())
    assert [g.gate for g in out.gates] == ["quality", "difficulty", "fairness", "cheat"]
    assert out.verdict == "ship with warnings"

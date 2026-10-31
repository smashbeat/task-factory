from pathlib import Path

from taskfactory.evidence import load_pack

PACK = Path(__file__).parent / "fixtures" / "coa-intake"


def test_items_come_from_the_manifest():
    pack = load_pack(PACK)
    assert len(pack.items) == 30
    assert pack.items["h11"].features == ("marker", "round_fail", "round_metal", "units")
    assert pack.items["h19"].route == "scan_ocr"
    assert "stamp_lot" in pack.sample_features and "stamp_retest" not in pack.sample_features


def test_trials_are_typed_by_job():
    pack = load_pack(PACK)
    kinds = sorted(t.kind for t in pack.trials)
    assert kinds.count("standard") == 6 and kinds.count("cheat") == 2
    assert kinds.count("oracle") == 2 and kinds.count("nop") == 2


def test_a_trial_carries_its_failed_items_and_diffs():
    pack = load_pack(PACK)
    t = pack.trial("JjKSvue")
    assert t.agent == "claude-code" and t.model == "anthropic/claude-opus-5-5"
    assert t.reward == 0 and t.total == 30 and t.correct == 28
    assert sorted(t.failed) == ["h11", "h19"]
    assert t.failed["h19"][0].field == "lot_number"
    assert 180 < t.minutes < 300


def test_static_checks_and_rubric():
    pack = load_pack(PACK)
    assert len(pack.static_checks) == 28 and all(ok for _, ok in pack.static_checks)
    assert len(pack.rubric_runs) == 8

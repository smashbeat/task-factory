"""The ported coa model must give exactly the answers coa-intake shipped with, seed 1."""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "packs" / "coa"))
import model  # noqa: E402

# gen2.py's fixed composition: id, house, route, lots, features
COMPOSITION = [
    ("s01", "hengxin", "digital", 2, {"alias"}),
    ("s02", "nordvik", "distilled", 2, {"units", "round_metal"}),
    ("s03", "pradesh", "scan_ocr", 1, {"nd_loq_col"}),
    ("s04", "bluewater", "form", 1, {"expired"}),
    ("s05", "hengxin", "digital", 1, {"rev_result", "rev_block", "continuation"}),
    ("s06", "nordvik", "distilled", 1, {"marker", "nd_loq_note"}),
    ("s07", "pradesh", "scan_ocr", 2, {"stamp_lot", "round_range"}),
    ("h01", "hengxin", "digital", 3, {"alias", "units", "round_metal", "continuation"}),
    ("h02", "hengxin", "digital", 1, {"rev_twice", "rev_block", "fail"}),
    ("h03", "hengxin", "digital", 2, {"nd_loq_note", "rev_result", "rev_page"}),
    ("h04", "pradesh", "outlined", 1, {"alias", "round_min"}),
    ("h05", "hengxin", "digital", 1, {"white_decoy", "expired"}),
    ("h06", "hengxin", "digital", 2, {"marker", "units_bad"}),
    ("h07", "hengxin", "digital", 1, {"annot_correction", "nd_loq_high"}),
    ("h08", "hengxin", "digital", 2, {"scramble", "round_range", "round_fail"}),
    ("h09", "nordvik", "distilled", 3, {"alias", "nd_no_loq"}),
    ("h10", "nordvik", "distilled", 2, {"rev_extends", "rev_page"}),
    ("h11", "nordvik", "distilled", 1, {"units", "round_metal", "round_fail", "marker"}),
    ("h12", "nordvik", "distilled", 2, {"continuation", "a4_continuation", "nd_loq_note", "wrap"}),
    ("h13", "nordvik", "outlined", 1, {"rev_result", "rev_block", "alias"}),
    ("h14", "nordvik", "distilled", 1, {"watermark", "missing", "alias"}),
    ("h15", "nordvik", "distilled", 2, {"stamp_retest", "expired"}),
    ("h16", "pradesh", "scan_wrong_ocr", 1, {"nd_loq_col", "round_min"}),
    ("h17", "pradesh", "scan_no_ocr", 2, {"alias", "units", "round_metal"}),
    ("h18", "pradesh", "scan_rotated", 1, {"stamp_lot", "fail"}),
    ("h19", "pradesh", "scan_ocr", 2, {"rev_result", "rev_block", "nd_loq_col"}),
    ("h20", "pradesh", "scan_ocr", 1, {"expired", "wrap"}),
    ("h21", "pradesh", "scan_no_ocr", 1, {"marker", "round_range"}),
    ("h22", "pradesh", "scan_wrong_ocr", 2, {"units", "units_bad"}),
    ("h23", "bluewater", "form_mismatch", 1, {"alias", "round_metal"}),
    ("h24", "bluewater", "form", 1, {"nd_loq_note", "marker"}),
    ("h25", "bluewater", "scan_ocr", 1, {"rev_extends", "rev_block"}),
    ("h26", "bluewater", "digital", 2, {"units", "nd_loq_high"}),
    ("h27", "bluewater", "outlined", 1, {"stamp_retest", "round_min", "round_fail"}),
    ("h28", "bluewater", "form_mismatch", 1, {"missing", "units"}),
    ("h29", "bluewater", "digital", 1, {"scramble", "rev_twice", "rev_block"}),
    ("h30", "bluewater", "digital", 2, {"watermark", "alias", "wrap", "continuation"}),
]


def test_model_reproduces_every_shipped_answer():
    for cid, house, route, lots, feats in COMPOSITION:
        c = model.Cert(cid, house, random.Random(f"1-{cid}"), lots, feats, route)
        model.apply_features(c)
        want = json.loads((ROOT / "tests" / "golden" / "coa-seed1" / f"{cid}.truth.json").read_text())
        assert c.truth() == want, cid


def test_each_switch_changes_some_answer():
    changed = set()
    for cid, house, route, lots, feats in COMPOSITION:
        c = model.Cert(cid, house, random.Random(f"1-{cid}"), lots, feats, route)
        model.apply_features(c)
        base = c.truth()
        for r in (3, 4, 5, 6, 7, 8):
            if c.truth(frozenset({r})) != base:
                changed.add(r)
    assert changed == {3, 4, 5, 6, 7, 8}


def test_missing_never_empties_a_marked_row():
    # holdout seed 1001, h28: the only candidate fell back to row 0, which carried the retest marker, so the page
    # printed a lone '*'
    sys.path.insert(0, str(ROOT / "packs" / "coa"))
    import pack
    c = pack.build("h28", "hengxin", "form_mismatch", 1, frozenset({"fail", "marker", "missing"}), random.Random("1001-h28"))
    rows = c.lots[0]["rows"]
    assert any(r["result"] is None for r in rows)
    assert not [r for r in rows if r["marker"] and r["result"] is None]

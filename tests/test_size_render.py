"""The size-set renderer, run in the pack's gen image. Skipped when the image is not built."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
IMAGE = "tf-size-set-gen:latest"
CASES = [
    ("stamp", "tablet", "digital", 3, ["stamp_value", "rev_twice"], "probe-stamp"),
    ("annot", "plm", "digital", 6, ["annot_correction", "fine_print"], "probe-annot"),
    ("form", "inspect", "form", 1, ["two_pieces"], "probe-form"),
    ("mismatch", "inspect", "form_mismatch", 1, ["comments_only"], "probe-mismatch"),
    ("landscape", "yongsheng", "scan_rotated", 6, ["size_order"], "probe-land"),
    ("a4", "tablet", "digital", 1, ["continuation", "a4_continuation"], "probe-a4"),
    ("remeasure", "inspect", "digital", 2, ["remeasure_page", "mixed_units"], "probe-rm"),
    ("glyph", "plm", "digital", 2, ["fraction_glyph"], "probe-glyph"),
    ("wrong", "yongsheng", "scan_wrong_ocr", 4, ["cm_report", "diff_wrong"], "probe-wrong"),
]
NUMBERISH = re.compile(r"^[\d/.¼½¾⅛⅜⅝⅞]+$")


@pytest.fixture(scope="module")
def drawn():
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        pytest.skip("gen image not built")
    r = subprocess.run(["docker", "run", "--rm", "--network", "none",
                        "-v", f"{ROOT / 'src'}:/tf/src:ro", "-v", f"{ROOT / 'packs' / 'size-set'}:/pack:ro",
                        "-v", f"{ROOT / 'tests' / 'probes'}:/probe:ro",
                        IMAGE, "python3", "/probe/size_render_probe.py", json.dumps(CASES)],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    errors = {k: v["error"] for k, v in out.items() if "error" in v}
    assert not errors, errors
    return out


@pytest.mark.parametrize("cid", [c[0] for c in CASES])
def test_drawing_leaves_the_truth_alone(drawn, cid):
    assert drawn[cid]["truth_same"]


def test_a_stamped_correction_covers_only_the_value_it_replaces(drawn):
    r = drawn["stamp"]
    assert r["images"] == 1
    assert 1 <= len(r["under_stamp"]) <= 2 and all(NUMBERISH.match(w) for w in r["under_stamp"]), r["under_stamp"]


def test_an_annotation_covers_only_the_printed_number(drawn):
    covered = drawn["annot"]["covered"]
    assert 1 <= len(covered) <= 2 and all(NUMBERISH.match(w) for w in covered), covered


def test_a_form_holds_one_field_per_measured_value(drawn):
    r = drawn["form"]
    assert len(r["fields"]) == 2 * len({k.split("|")[0] for k in r["measured"]})
    assert all(re.search(r"\d", v) for _, v in r["fields"])


def test_a_mismatched_form_stores_other_values_than_it_prints(drawn):
    r = drawn["mismatch"]
    printed = {v for v in r["measured"].values() if v}
    assert r["fields"] and not any(v in printed for _, v in r["fields"]), r["fields"]


def test_a_sideways_scan_of_a_landscape_report_is_portrait(drawn):
    assert all((w, h) == (595, 842) for w, h, _ in drawn["landscape"]["pages"]), drawn["landscape"]["pages"]


def test_the_continuation_page_changes_size(drawn):
    assert [(w, h) for w, h, _ in drawn["a4"]["pages"]] == [(612, 792), (595, 842)]


def test_a_re_measurement_page_is_dated_and_states_its_unit(drawn):
    r = drawn["remeasure"]
    assert len(r["pages"]) >= 2
    assert "re-measurement" in r["text"].lower()
    assert re.search(r"values in (centimetres|inches)", r["text"].lower()) or re.search(r"stated in", r["text"].lower())


def test_fraction_glyphs_print_as_glyphs(drawn):
    assert drawn["glyph"]["glyphs"] > 0


def test_the_wrong_ocr_layer_differs_from_the_page(drawn):
    r = drawn["wrong"]
    assert "altered values" in r["note"]

"""The coa renderer, run in the pack's gen image. Skipped when the image is not built."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
IMAGE = "tf-coa-intake-gen:latest"
CASES = [
    ("a1", "pradesh", "digital", 1, ["annot_correction", "stamp_retest"], "probe-a1"),
    ("a2", "nordvik", "digital", 1, ["annot_correction"], "probe-a2"),
    ("a3", "hengxin", "digital", 1, ["annot_correction"], "probe-a3"),
    # holdout seed 1001: the corrected row fell on the continuation page
    ("h19", "bluewater", "digital", 1, ["a4_continuation", "annot_correction", "continuation", "watermark"], "1001-h19"),
    # holdout seed 5001: a scrambled table dropped the marked row's mark and unit ("0.34" for "0.34ᵃ %")
    ("h16", "nordvik", "distilled", 2, ["marker", "scramble", "units_bad"], "5001-h16"),
    # build seed 4001: the retest stamp sat over the end of "Calcium Carbonate (Precipitated)"
    ("h03", "nordvik", "digital", 2, ["continuation", "marker", "rev_page", "rev_twice", "round_metal", "stamp_retest"],
     "4001-h03"),
    ("s07", "pradesh", "digital", 1, ["nd_loq_high", "stamp_lot", "watermark"], "4001-s07"),
]


@pytest.fixture(scope="module")
def drawn():
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        pytest.skip("gen image not built")
    r = subprocess.run(["docker", "run", "--rm", "--network", "none",
                        "-v", f"{ROOT / 'packs' / 'coa'}:/pack:ro", "-v", f"{ROOT / 'tests' / 'probes'}:/probe:ro",
                        IMAGE, "python3", "/probe/coa_render_probe.py", json.dumps(CASES)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_stamp_survives_the_correction_redraw(drawn):
    assert drawn["a1"]["images"] >= 1


@pytest.mark.parametrize("cid", ["a1", "a2", "a3", "h19"])
def test_correction_covers_only_the_printed_number(drawn, cid):
    covered = drawn[cid]["covered"]
    assert len(covered) == 1 and covered[0].replace(".", "").isdigit(), covered


def test_a_scrambled_row_keeps_its_mark_and_unit(drawn):
    line = drawn["h16"]["marked_line"]
    assert "".join(line) == "0.34a%", line          # the superscript mark reads as part of the number


@pytest.mark.parametrize("cid", ["a1", "h03", "s07"])
def test_a_stamp_covers_no_printed_word(drawn, cid):
    assert drawn[cid]["images"] >= 1
    assert drawn[cid]["under_stamp"] == [], drawn[cid]["under_stamp"]

"""The coa renderer, run in the pack's gen image. Skipped when the image is not built."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
IMAGE = "tf-coa-intake-gen:latest"
CASES = [
    ("a1", "pradesh", "digital", 1, ["annot_correction", "stamp_retest"]),
    ("a2", "nordvik", "digital", 1, ["annot_correction"]),
    ("a3", "hengxin", "digital", 1, ["annot_correction"]),
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


@pytest.mark.parametrize("cid", ["a1", "a2", "a3"])
def test_correction_covers_only_the_printed_number(drawn, cid):
    covered = drawn[cid]["covered"]
    assert len(covered) == 1 and covered[0].replace(".", "").isdigit(), covered

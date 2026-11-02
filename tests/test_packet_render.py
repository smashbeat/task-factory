"""The packet-log renderer, run in the pack's gen image. Skipped when the image is not built."""
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
IMAGE = "tf-packet-log-gen:latest"
CASES = [
    ("lie", "sdr", "header_lie", 3, ["msg_ack", "digi_h"], "probe-lie"),
    ("decoy", "tnc2", "stereo_decoy", 2, ["dup_retry"], "probe-decoy"),
    ("mobile", "mobile", "qsb", 3, ["latin1", "status_frame"], "probe-mobile"),
    ("corrupt", "handheld", "clean", 3, ["shared_flag", "bad_fcs", "abort", "ssid_hi"], "probe-corrupt"),
    ("hard", "tnc2", "stack", 4, ["msg_retry", "long_info"], "probe-hard"),
]


@pytest.fixture(scope="module")
def rendered():
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        pytest.skip("gen image not built")
    r = subprocess.run(["docker", "run", "--rm", "--network", "none",
                        "-v", f"{ROOT / 'packs' / 'packet-log'}:/pack:ro", "-v", f"{ROOT / 'tests' / 'probes'}:/probe:ro",
                        IMAGE, "python3", "/probe/packet_render_probe.py", json.dumps(CASES)],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("cid", [c[0] for c in CASES])
def test_direwolf_hears_every_valid_frame_on_the_radio_channel(rendered, cid):
    got, want = rendered[cid]["decoded_radio"], rendered[cid]["expected"]
    assert Counter(got) == Counter(want), (got, want)


def test_the_header_lies_about_the_rate_and_the_samples_do_not(rendered):
    r = rendered["lie"]
    assert r["header"]["rate"] == r["declared_rate"] != r["true_rate"]
    assert 0 <= r["header"]["seconds"] - r["duration"] <= 1.5   # the file runs a little past the last frame


def test_the_other_channel_carries_only_the_decoy(rendered):
    r = rendered["decoy"]
    assert r["header"]["channels"] == 2 and r["decoys"]
    assert Counter(r["decoded_other"]) == Counter(r["decoys"])
    assert not set(r["decoded_radio"]) & set(r["decoys"])


def test_the_mobile_recorder_writes_eight_bit_mono(rendered):
    r = rendered["mobile"]
    assert r["header"] == {**r["header"], "bits": 8, "channels": 1, "rate": 11025}


def test_corrupt_frames_are_on_the_air_but_never_decode(rendered):
    r = rendered["corrupt"]
    assert r["corrupt"] == 2 and len(r["decoded_radio"]) == len(r["expected"])

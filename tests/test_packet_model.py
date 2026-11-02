"""The packet-log pack's model: frames encode to AX.25 bytes that decode back, and the truth follows the rules."""
import importlib.util
import random
from pathlib import Path

import pytest

PACK = Path(__file__).parent.parent / "packs" / "packet-log"
# loaded under its own name: the coa pack's model.py shares the plain name `model`
_spec = importlib.util.spec_from_file_location("packet_log_model", PACK / "model.py")
model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(model)


def capture(features, n=None, route="clean", house="tnc2", seed="t"):
    feats = set(features)
    n = n or model.min_units(feats)
    return model.Capture("x", house, random.Random(seed), n, feats, route)


def test_fcs_is_crc16_x25():
    assert model.crc16_x25(b"123456789") == 0x906E


def test_a_frame_decodes_back_to_its_fields():
    tx = model.Tx(("N0CALL", 9), ("APDR16", 0), [("WIDE1", 1, True), ("WIDE2", 1, False)], b"!3404.52N/11814.62W>hi")
    p = model.parse_frame(tx.bytes)
    assert p["source"] == ("N0CALL", 9) and p["destination"] == ("APDR16", 0)
    assert p["path"] == [("WIDE1", 1, True), ("WIDE2", 1, False)]
    assert p["pid"] == 0xF0 and p["info"] == b"!3404.52N/11814.62W>hi"
    assert tx.tnc2() == "N0CALL-9>APDR16,WIDE1-1*,WIDE2-1:!3404.52N/11814.62W>hi"
    assert model.parse_frame(tx.bytes[:-1] + bytes([tx.bytes[-1] ^ 1])) is None


def test_stuffing_inserts_a_zero_after_five_ones():
    bits = model.hdlc_bits(bytes([0xFF]))
    assert bits == [1, 1, 1, 1, 1, 0, 1, 1, 1]


def test_duplicate_within_30_s_points_at_the_first_frame_and_a_late_copy_does_not():
    c = capture({"dup_retry"})
    t = c.truth()
    dups = [f for f in t["frames"] if f["dup_of"] is not None]
    assert len(dups) == 1 and t["frames"][dups[0]["dup_of"]]["info"] == dups[0]["info"]
    c = capture({"dup_late"})
    assert all(f["dup_of"] is None for f in c.truth()["frames"])
    assert len({f["info"] for f in c.truth()["frames"]}) == 1


def test_a_message_is_acked_only_by_its_addressee_with_its_id():
    acked = capture({"msg_ack"}).truth()["messages"]
    assert len(acked) == 1 and acked[0]["status"] == "acked" and acked[0]["sent"] == 1
    other = capture({"ack_other"}).truth()["messages"]
    assert other[0]["status"] == "open"
    retry = capture({"msg_retry"}).truth()
    assert retry["messages"][0]["sent"] == 3
    assert sum(f["dup_of"] is not None for f in retry["frames"]) == 1


def test_the_latest_position_wins():
    t = capture({"pos_update"}).truth()
    pos = [f for f in t["frames"] if f["kind"] == "position"]
    assert t["positions"][pos[0]["source"]]["t_ms"] == max(f["t_ms"] for f in pos)


def test_corrupt_frames_are_not_reported_and_the_log_may_lie():
    c = capture({"bad_fcs", "abort", "log_typo", "log_extra"}, n=3)
    t = c.truth()
    assert len(t["frames"]) == 3
    assert len(c.frames_all) == 5
    spec = c.spec()
    assert set(spec) == {"station", "radio_channel", "sample_rate", "heard"}
    assert len(spec["heard"]) == 4   # three heard plus the line that was never sent


def test_every_mutant_rule_changes_the_answer_on_its_own_feature():
    cases = {2: ({"bad_fcs"}, "clean"), 3: ({"digi_h"}, "clean"), 4: ({"non_ui"}, "clean"),
             5: ({"dup_retry"}, "clean"), 6: ({"msg_ack"}, "clean"), 7: ({"pos_update"}, "clean")}
    for rule, (feats, route) in cases.items():
        c = capture(feats, route=route)
        assert c.truth(frozenset({rule})) != c.truth(), f"rule {rule} not decided by {feats}"
    lie = capture(set(), n=2, route="header_lie")
    assert lie.truth(frozenset({2})) != lie.truth()
    decoy = capture(set(), n=2, route="stereo_decoy", house="sdr")
    assert len(decoy.truth(frozenset({2}))["frames"]) > len(decoy.truth()["frames"])


def test_times_follow_the_bit_count_and_the_senders_baud():
    c = capture(set(), n=2, route="drift")
    assert c.baud != model.BAUD
    for tx in c.txs:
        assert c.end_ms(tx) == int(round((tx.burst_start + tx.end_bits / c.baud) * 1000))


def test_truth_is_deterministic_per_seed():
    a = capture({"msg_ack", "digi_h", "quiet_tx"}, n=4, route="stack", house="handheld", seed="d")
    b = capture({"msg_ack", "digi_h", "quiet_tx"}, n=4, route="stack", house="handheld", seed="d")
    assert a.truth() == b.truth() and a.spec() == b.spec()


def test_a_capture_refuses_too_few_frames_for_its_features():
    with pytest.raises(ValueError):
        capture({"msg_retry"}, n=2)

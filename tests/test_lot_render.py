"""The lot-release renderer, run in the pack's gen image. Skipped when the image is not built."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
IMAGE = "tf-lot-release-gen:latest"
CASES = [
    ("c1", "sierra", "digital", 3, ["clean"], "probe-c1"),
    ("c2", "meridian", "digital", 2, ["eml_reply_supersedes", "eml_forwarded", "cell_format", "label_outlined"], "probe-c2"),
    ("c3", "kestrel", "scan_ocr", 2, ["two_sheets", "hidden_row", "csv_semicolon", "void_document"], "probe-c3"),
    ("c4", "sierra", "distilled", 2, ["eml_two_attachments", "text_number", "total_lies", "label_revision", "member_scan"], "probe-c4"),
    ("c5", "meridian", "form", 1, ["coa_fail", "lot_mismatch"], "probe-c5"),
    ("c6", "kestrel", "outlined", 3, ["extra_certificate", "coa_two_lots", "eml_body_lies", "stamp_lot"], "probe-c6"),
]


@pytest.fixture(scope="module")
def drawn():
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        pytest.skip("gen image not built")
    r = subprocess.run(["docker", "run", "--rm", "--network", "none",
                        "-v", f"{ROOT / 'src'}:/tf/src:ro", "-v", f"{ROOT / 'packs' / 'lot-release'}:/pack:ro",
                        "-v", f"{ROOT / 'tests' / 'probes'}:/probe:ro",
                        IMAGE, "python3", "/probe/lot_render_probe.py", json.dumps(CASES)],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("cid", [c[0] for c in CASES])
def test_every_package_renders_its_planned_files_and_keeps_its_truth(drawn, cid):
    d = drawn[cid]
    assert d["files"] == d["planned"], (d["files"], d["planned"])
    assert d["truth_unchanged"]
    assert 0 < d["pdf_pages"] <= 12
    assert all(s["formulas"] == 0 for s in d["xlsx"]["sheets"])
    assert d["csv"]["crlf"]


def test_clean_sierra_package(drawn):
    d = drawn["c1"]
    titles = [s["title"] for s in d["xlsx"]["sheets"]]
    assert titles == ["Batch", "Dispensing"] and all(s["state"] == "visible" and not s["hidden_rows"] for s in d["xlsx"]["sheets"])
    assert d["xlsx"]["creator"] == "Sierra ERP 9.2"
    disp = [c for c in d["xlsx"]["sheets"][1]["cells"] if c["ref"].startswith("E") and c["type"] == "n"]
    assert len(disp) >= 3 and all(c["format"] != "General" for c in disp)
    dates = [c for c in d["xlsx"]["sheets"][0]["cells"] if c["type"] == "d"]
    assert len(dates) == 1 and dates[0]["format"] == "yyyy-mm-dd"
    assert d["csv"]["delimiter"] == "," and d["csv"]["rows"][0][0] == "Lot" and d["csv"]["rows"][-1][0] == "TOTAL"
    assert "LOT" in d["label"]["text"] and "Supplement Facts" in d["label"]["text"]
    assert all(e["attachments"] for e in d["emails"].values())


def test_meridian_reply_forward_and_edge_cell(drawn):
    d = drawn["c2"]
    emails = d["emails"]
    replies = [e for e in emails.values() if e["in_reply_to"]]
    forwards = [e for e in emails.values() if e["forwarded"]]
    assert len(replies) == 1 and len(forwards) == 1
    orig = next(e for e in emails.values() if e["subject"] == replies[0]["subject"].removeprefix("Re: ") and not e["in_reply_to"])
    assert replies[0]["ts"] > orig["ts"]
    assert forwards[0]["inner_attachments"]
    assert all(a[1] == "message/rfc822" for a in forwards[0]["attachments"]), "the forward carries only the inner message"
    assert d["label"]["text"].strip() == "", "outlined label must have no text layer"
    log = next(s for s in d["xlsx"]["sheets"] if s["title"].startswith("Dispensing"))
    edge = [c for c in log["cells"] if c["type"] == "n" and c["format"] in ("0.00", "0") and "." in str(c["value"])]
    assert edge, "the edge cell shows one place fewer than it stores"
    assert d["csv"]["bom"]


def test_kestrel_scanned_package_with_void_sheet_or_rows(drawn):
    d = drawn["c3"]
    sheets = d["xlsx"]["sheets"]
    assert any(s["title"].endswith("(2)") for s in sheets)
    assert any(s["hidden_rows"] for s in sheets)
    void = any("VOID" in s["title"] for s in sheets) or any(c["value"] == "VOID" for s in sheets for c in s["cells"])
    void_cert = "void" in d["note"]
    assert void or void_cert
    assert d["csv"]["delimiter"] == ";" and any("," in cell for row in d["csv"]["rows"][1:] for cell in row[3:])
    scans = [p for n, p in d["pdfs"].items() if n != d["planned"][0] and "artwork" not in n]
    assert scans and all(p["images"] >= 1 and p["text"] > 0 for p in scans), "certificates and the report are OCR'd scans"


def test_sierra_distilled_with_two_attachments_and_text_number(drawn):
    d = drawn["c4"]
    assert any(len(e["attachments"]) == 2 for e in d["emails"].values())
    log = next(s for s in d["xlsx"]["sheets"] if s["title"] == "Dispensing")
    assert any(c["type"] == "s" and "," in str(c["value"]) and c["ref"].startswith("E") for c in log["cells"])
    assert "Artwork revisions" in d["label"]["text"]
    member = [p for p in d["pdfs"].values() if p["images"] >= 1]
    assert member, "one certificate came as a scan inside a distilled package"


def test_meridian_form_certificate(drawn):
    d = drawn["c5"]
    certs = [p for n, p in d["pdfs"].items() if ".eml" in n or n not in (d["planned"][0],)]
    assert any(p["widgets"] > 0 for p in d["pdfs"].values()), "a form route certificate carries fields"


def test_kestrel_outlined_with_extra_certificate_and_lying_body(drawn):
    d = drawn["c6"]
    n_certs = len([n for n in d["pdfs"] if n != "" and not n.endswith("-artwork.pdf") and not n.endswith("-release.pdf")])
    assert n_certs == 4, d["pdfs"].keys()
    assert any("Assay" in e["body"] for e in d["emails"].values())
    assert all(p["text"] == 0 for n, p in d["pdfs"].items() if not n.endswith("-artwork.pdf")), "outlined pages have no text layer"
    assert d["label"]["text"].strip(), "the label stays digital unless label_outlined says so"

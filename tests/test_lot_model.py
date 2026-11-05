"""The lot-release model: numbers, dates, precedence, the decision ladder, and the builder gates on seed 1."""
import datetime as dt
import random
import sys
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from taskfactory.builder.corpus import make_corpus
from taskfactory.builder.gates import corpus_gate, pack_gate, spec_gate
from taskfactory.builder.pack import load_domain
from taskfactory.builder.plan import make_plan

ROOT = Path(__file__).parent.parent
PACK = ROOT / "packs" / "lot-release"
model = load_domain(PACK).module.model   # through the loader, so this pack's `model` wins over another pack's


def _package(seed=11, style="sierra", units=3, features=(), route="digital"):
    p = model.Package(f"t{seed}", style, random.Random(seed), units, set(features), route)
    model.apply_features(p)
    return p


def test_mass_conversion_and_half_up_rounding():
    assert model.convert_mass(D("12.5"), "kg", "g") == D("12500")
    assert model.convert_mass(D("250"), "mg", "g") == D("0.25")
    assert model.round_places(D("1.2345"), 3) == D("1.235")
    assert model.round_places(D("1.2344"), 3) == D("1.234")
    assert model.shown(D("12.4999"), "0.00") == D("12.50") and model.shown(D("1250.5"), "#,##0") == D("1251")


def test_add_months_clamps_to_the_month_end():
    assert model.add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert model.add_months(dt.date(2026, 8, 31), 18) == dt.date(2028, 2, 29)
    assert model.add_months(dt.date(2026, 5, 15), 24) == dt.date(2028, 5, 15)
    assert model.add_months(dt.date(2026, 3, 31), 36) == dt.date(2029, 3, 31)


def test_lot_numbers_compare_as_strings_without_hyphens():
    assert model.lot_key("L-00123") == model.lot_key("l00123") != model.lot_key("L123")


def test_a_clean_package_is_released():
    p = _package(features={"clean"})
    t = p.truth()
    assert t["findings"] == [] and t["decision"] == "released"
    assert len(t["ingredients"]) == 3 and all(r["certificate"] == "ok" for r in t["ingredients"])
    assert t["expires_on"] == model.add_months(p.manufactured_on, p.shelf_life).isoformat()
    assert t["packing"]["units"] == t["yield"]


def test_tolerance_is_inclusive_after_rounding():
    p = _package(features={"qty_tolerance"})
    t = p.truth()
    on_edge = any("on the tolerance" in n for n in p.notes)
    has_quantity = any(f.startswith("quantity:") for f in t["findings"])
    assert on_edge != has_quantity


def test_cell_format_decides_by_what_the_cell_shows():
    p = _package(features={"cell_format"})
    t = p.truth()
    assert not any(f.startswith("quantity:") for f in t["findings"])
    assert any(f.startswith("quantity:") for f in p.truth(frozenset({2}))["findings"])


def test_status_precedence_and_every_finding_listed():
    p = _package(seed=5, units=1, features={"unapproved_supplier", "coa_fail"})
    t = p.truth()
    row = t["ingredients"][0]
    assert row["certificate"] == "unapproved"
    kinds = {f.split(":")[0] for f in t["findings"]}
    assert {"supplier_unapproved", "certificate_fail"} <= kinds
    assert t["decision"] == "rejected"


def test_hold_and_reject_classes():
    p = _package(seed=8, features={"packing_mismatch"})
    assert p.truth()["decision"] == "hold"
    q = _package(seed=8, features={"packing_mismatch", "reject_and_hold"})
    t = q.truth()
    kinds = {f.split(":")[0] for f in t["findings"]}
    assert kinds & set(model.REJECTS) and kinds - set(model.REJECTS) and t["decision"] == "rejected"


def test_reply_supersedes_across_time_zones():
    p = _package(seed=21, units=1, features={"eml_reply_supersedes"})
    assert len(p.certs) == 2 and len(p.emails) == 2
    first, reply = p.emails
    assert reply["reply_of"] == 0 and reply["date"] > first["date"]
    standing = p._standing(frozenset())
    assert len(standing) == 1 and standing[0]["email"] == 1
    # the mutant that takes the first by file name stands on the other one for some seed
    assert p.truth() != p.truth(frozenset({7})) or p.certs[0]["name"] > p.certs[1]["name"]


def test_forwarded_certificate_is_dated_by_the_inner_message():
    p = _package(seed=3, units=2, features={"eml_forwarded"})
    fwd = next(e for e in p.emails if e["forward_of"] is not None)
    inner = p.emails[fwd["forward_of"]]
    assert inner["embedded"] and fwd["date"] > inner["date"]
    assert all(p._cert_date(d) == inner["date"] for d in p.certs if d["email"] == fwd["forward_of"])


def test_expiry_month_end_and_label_mcg():
    p = _package(seed=2, features={"expiry_month_end", "label_mcg"})
    t = p.truth()
    assert not any(f.startswith("label_amount") for f in t["findings"])
    assert any(f.startswith("label_amount") for f in p.truth(frozenset({8}))["findings"])


def test_void_variants_do_not_change_the_truth_but_the_mutant_does():
    seen = set()
    for seed in range(1, 40):
        p = _package(seed=seed, units=2, features={"void_document"})
        seen.add(p.workbook.get("void_variant"))
        assert p.truth() != p.truth(frozenset({7})), (seed, p.workbook.get("void_variant"))
    assert seen == {"sheet", "rows", "certificate"}


def test_file_inventory_matches_the_kinds():
    for style in model.STYLES:
        p = _package(seed=13, style=style, features={"eml_two_attachments", "extra_certificate"})
        kinds = [f["kind"] for f in p.files]
        assert kinds.count("workbook") == 1 and kinds.count("csv") == 1 and kinds.count("label") == 1
        assert kinds.count("report") == 1
        names = [f["name"] for f in p.files]
        assert len(names) == len(set(names)) and all(n for n in names)
        assert kinds.count("cert") + sum(len(e["attachments"]) for e in p.emails if not e["embedded"]) >= len(p.certs) - 1


@pytest.fixture(scope="module")
def pack():
    return load_domain(PACK)


def test_pack_gate_passes(pack):
    g = pack_gate(pack)
    assert g.status != "fail", [f.text for f in g.findings if f.level == "fail"]
    assert len(pack.rules) == 12 and len(pack.features) == 46
    assert pack.seconds == 300 and pack.scan_dpi == 200 and pack.ext == "pkg"


def test_seed_1_plan_and_corpus_pass_the_gates(pack):
    # the build loop tries three compositions of a seed before it stops; one of them must pass both gates
    failures = []
    for attempt in range(3):
        plan = make_plan(pack, seed=1, attempt=attempt)
        g = spec_gate(pack, plan)
        if g.status == "fail":
            failures.append((attempt, [f.text for f in g.findings if f.level == "fail"]))
            continue
        corpus = make_corpus(pack, plan, 1)
        g = corpus_gate(pack, plan, corpus, 1)
        if g.status == "fail":
            failures.append((attempt, [f.text for f in g.findings if f.level == "fail"]))
            continue
        break
    else:
        pytest.fail(f"no composition of seed 1 passed: {failures}")
    for it in plan.samples + plan.hidden:
        p = pack.module.build(it.id, it.style, it.route, it.units, it.features, random.Random(f"1-{it.id}"))
        assert p.pdf_pages() <= 12, (it.id, p.pdf_pages())
        assert len({f["name"] for f in p.files}) == len(p.files), it.id


def test_valid_holds_the_page_cap_and_the_route_rules(pack):
    heavy = frozenset({"two_lots_dispensed", "extra_certificate", "eml_reply_supersedes", "void_document", "coa_two_lots"})
    assert pack.module._pages(4, set(heavy)) <= 12 and pack.module.valid("sierra", "digital", 4, heavy)
    assert not pack.module.valid("sierra", "digital", 6, heavy)          # two ingredients more would pass the cap
    assert not pack.module.valid("sierra", "scan_ocr", 2, frozenset({"member_scan"}))
    assert not pack.module.valid("sierra", "form", 2, frozenset({"coa_two_lots"}))
    assert not pack.module.valid("sierra", "digital", 1, frozenset({"hidden_row"}))

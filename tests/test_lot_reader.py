"""The lot-release reference's readers on the inputs the spec implies but the generator never writes:
a BOM and CRLF, an attachment that is not a PDF, a Date header that will not parse, a cell format it never saw."""
import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from openpyxl import Workbook

from taskfactory.forge.office import write_csv, write_eml

PACK = Path(__file__).parent.parent / "packs" / "lot-release"


@pytest.fixture(scope="module")
def ref():
    pytest.importorskip("pytesseract")
    spec = importlib.util.spec_from_file_location("lot_ref", PACK / "task" / "solution" / "intake.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_csv_with_bom_crlf_and_either_habit(ref, tmp_path):
    p = tmp_path / "pack.csv"
    header = ["Lot", "Expiry", "Pallet", "Cases", "Units per Case", "Loose Units", "Gross kg", "Packed On", "Total Units"]
    rows = [["SNL-260417", "2028-03-09", 1, 120, 24, 0, Decimal("136.5"), "2026-03-14", 2880],
            ["SNL-260417", "2028-03-09", 2, 125, 24, 7, Decimal("142.0"), "2026-03-14", 3007],
            ["TOTAL", "", "", 245, "", 7, Decimal("278.5"), "", 5887]]
    write_csv(p, header, rows, bom=True)
    r = ref.read_packing(p)
    assert (r["lot"], r["expiry"], r["units"]) == ("SNL-260417", "2028-03-09", 5887)
    write_csv(p, header, [[*rows[0][:3], 1250, 24, 7, Decimal("1812.5"), "14-Mar-2026", 30007]], delimiter=";", decimal=",", thousands=".")
    r = ref.read_packing(p)
    assert r["units"] == 1250 * 24 + 7


def test_email_skips_other_attachments_and_survives_a_bad_date(ref, tmp_path):
    pdf = b"%PDF-1.4 fake"
    when = dt.datetime(2026, 3, 2, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    p = tmp_path / "a.eml"
    write_eml(p, frm="qc@x.example", to="qa@y.example", subject="CoA", date=when, body="hi",
              attachments=[("photo.png", b"\x89PNG....", "image/png"), ("coa.pdf", pdf, "application/pdf")])
    got = ref.read_email(p)
    assert len(got) == 1 and got[0][0] == pdf and got[0][1] == when
    raw = p.read_bytes().replace(b"Date: ", b"Date: not a date, honestly ")
    (tmp_path / "b.eml").write_bytes(raw)
    got = ref.read_email(tmp_path / "b.eml")
    assert len(got) == 1 and got[0][1] is None


def test_unknown_number_format_reads_the_stored_value(ref, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = 12.4999
    ws["A1"].number_format = "0.00"
    ws["A2"] = 12.4999                      # General
    ws["A3"] = 1250.5
    ws["A3"].number_format = "#,##0"
    ws["A4"] = "12,500.0"
    ws["A5"] = 7
    ws["A5"].number_format = '[$-409]"ea "0;@'  # a format the generator never writes: zero places shown
    wb.save(tmp_path / "x.xlsx")
    from openpyxl import load_workbook
    ws = load_workbook(tmp_path / "x.xlsx", data_only=True).active
    assert ref.shown(ws["A1"]) == Decimal("12.50") and ref.shown(ws["A2"]) == Decimal("12.4999")
    assert ref.shown(ws["A3"]) == Decimal("1251") and ref.shown(ws["A4"]) == Decimal("12500.0")
    assert ref.shown(ws["A5"]) == Decimal("7")
    assert ref.fmt_places("General") is None and ref.fmt_places("0.000000") == 6


def test_lot_keys_and_month_arithmetic(ref):
    assert ref.lkey("L-00123") == ref.lkey("l00123") != ref.lkey("L123")
    assert ref.add_months(dt.date(2026, 8, 31), 18) == dt.date(2028, 2, 29)
    assert ref.to_unit(Decimal("250000"), "mcg", "mg") == Decimal("250")

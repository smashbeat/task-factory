"""The office writers: a workbook, a CSV and an email file that read back as the model says."""
import datetime as dt
import email
import email.policy
import email.utils
from decimal import Decimal
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from taskfactory.forge.office import Sheet, write_csv, write_eml, write_xlsx


def test_workbook_round_trip(tmp_path):
    rows = [
        ["Dispensing log", None, None, None, None],
        ["Code", "Material", "Dispensed", "Unit", "Date"],
        ["ING-01", "Ascorbic Acid USP", Decimal("12.4999"), "kg", dt.date(2026, 3, 9)],
        ["ING-02", "Zinc Citrate Trihydrate", Decimal("1250.5"), "g", dt.date(2026, 3, 9)],
        ["Total", None, Decimal("1263.0"), None, None],
    ]
    log = Sheet("Dispensing", rows, formats={2: "0.00", (3, 2): "#,##0.0"}, merged=["A1:E1"],
                hidden_rows=[3], bold_rows=[1], widths={1: 28})
    old = Sheet("VOID Dispensing", rows[1:4], hidden=True)
    write_xlsx(tmp_path / "br.xlsx", [log, old], props={"creator": "Sierra ERP 9.2", "title": "Batch record"})
    wb = load_workbook(tmp_path / "br.xlsx", data_only=True)
    ws = wb["Dispensing"]
    assert ws["C3"].value == 12.4999 and ws["C3"].number_format == "0.00"
    assert ws["C4"].value == 1250.5 and ws["C4"].number_format == "#,##0.0"
    assert ws["C5"].number_format == "0.00"
    assert ws["E3"].value == dt.datetime(2026, 3, 9) and ws["E3"].is_date
    assert ws["A3"].value == "ING-01" and ws["B2"].font.bold and not ws["B3"].font.bold
    assert ws.row_dimensions[4].hidden and not ws.row_dimensions[3].hidden
    assert "A1:E1" in {str(r) for r in ws.merged_cells.ranges}
    assert ws.column_dimensions["B"].width == 28
    assert wb["VOID Dispensing"].sheet_state == "hidden"
    assert wb.properties.creator == "Sierra ERP 9.2" and wb.properties.title == "Batch record"
    assert all(c.data_type != "f" for row in ws.iter_rows() for c in row)


def test_csv_habits(tmp_path):
    p = tmp_path / "pack.csv"
    write_csv(p, ["lot", "cases", "gross_kg"], [["24-0871", 1250, Decimal("812.5")]])
    assert p.read_bytes() == b"lot,cases,gross_kg\r\n24-0871,1250,812.5\r\n"
    write_csv(p, ["lot", "cases", "gross_kg"], [["24-0871", 1250, Decimal("812.5")]],
              delimiter=";", decimal=",", thousands=".", bom=True)
    assert p.read_bytes() == "﻿".encode() + b"lot;cases;gross_kg\r\n24-0871;1.250;812,5\r\n"
    write_csv(p, ["a", "b"], [["x, y", 7]], quote_all=True)
    assert p.read_bytes() == b'"a","b"\r\n"x, y","7"\r\n'


def test_email_round_trip(tmp_path):
    pdf = b"%PDF-1.4 fake certificate"
    when = dt.datetime(2026, 3, 2, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    first = tmp_path / "coa.eml"
    mid = write_eml(first, frm="QC <qc@hengxin-nutrition.example>", to="qa@sierra-nutra.example",
                    subject="CoA for Batch B481220", date=when, body="Dear QA,\n\nPlease find the certificate attached.\n",
                    attachments=[("CoA_B481220.pdf", pdf, "application/pdf")])
    msg = email.message_from_bytes(first.read_bytes(), policy=email.policy.default)
    atts = list(msg.iter_attachments())
    assert [a.get_filename() for a in atts] == ["CoA_B481220.pdf"] and atts[0].get_content() == pdf
    assert atts[0].get_content_type() == "application/pdf"
    assert email.utils.parsedate_to_datetime(msg["Date"]) == when
    assert msg["Message-ID"] == mid and msg.get_body(("plain",)).get_content().startswith("Dear QA")

    later = when + dt.timedelta(days=1, hours=2)
    reply = tmp_path / "coa-corrected.eml"
    write_eml(reply, frm="QC <qc@hengxin-nutrition.example>", to="qa@sierra-nutra.example",
              subject="Re: CoA for Batch B481220", date=later, body="Corrected certificate attached.\n",
              attachments=[("CoA_B481220_rev2.pdf", pdf + b" rev2", "application/pdf")], in_reply_to=mid)
    r = email.message_from_bytes(reply.read_bytes(), policy=email.policy.default)
    assert r["In-Reply-To"] == mid and mid in r["References"]
    assert email.utils.parsedate_to_datetime(r["Date"]) > email.utils.parsedate_to_datetime(msg["Date"])

    fwd = tmp_path / "fwd.eml"
    write_eml(fwd, frm="Purchasing <buy@sierra-nutra.example>", to="qa@sierra-nutra.example",
              subject="Fwd: CoA for Batch B481220", date=later + dt.timedelta(hours=5),
              body="Forwarding the supplier's mail.\n", forward=first)
    f = email.message_from_bytes(fwd.read_bytes(), policy=email.policy.default)
    inner = [p for p in f.walk() if p.get_content_type() == "message/rfc822"]
    assert len(inner) == 1
    forwarded = inner[0].get_content()
    assert forwarded["Message-ID"] == mid
    assert [a.get_content() for a in forwarded.iter_attachments()] == [pdf]
    assert not list(f.iter_attachments()) or all(a.get_content_type() == "message/rfc822" for a in f.iter_attachments())

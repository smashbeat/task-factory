"""Office-file writers for packs whose items hold more than PDFs: a workbook, a CSV and an email file.

Each writer stores exactly what the model says and nothing it does not: a workbook cell is a typed stored value
with a number format (never a formula), a CSV line is text in one of two number habits, an email is a MIME
message whose attachments are the documents. The readers in the packs' tests check that each file reads back
as it was written.
"""
from __future__ import annotations

import csv
import datetime as dt
import email.policy
import email.utils
import io
from dataclasses import dataclass, field
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

Cell = str | int | Decimal | dt.date | None


@dataclass
class Sheet:
    """One worksheet. `rows` are lists of cells, row 0 at the top. `formats` maps a column index, or a
    (row, column) pair, to a number format applied to the numeric and date cells there; a pair wins over its
    column. Indices are zero-based."""
    title: str
    rows: list[list[Cell]]
    formats: dict = field(default_factory=dict)
    merged: list[str] = field(default_factory=list)       # ranges in A1 notation, "A1:E1"
    hidden_rows: list[int] = field(default_factory=list)
    hidden: bool = False
    widths: dict = field(default_factory=dict)            # column index -> width in characters
    bold_rows: list[int] = field(default_factory=list)


def _store(value: Cell):
    """A workbook stores text, integers, doubles and dates: a Decimal becomes the double Excel would hold."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return dt.datetime(value.year, value.month, value.day)
    return value


def write_xlsx(path, sheets: list[Sheet], props: dict | None = None) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for sh in sheets:
        ws = wb.create_sheet(sh.title)
        bold = Font(bold=True)
        for r, row in enumerate(sh.rows):
            for c, value in enumerate(row):
                if value is None:
                    continue
                cell = ws.cell(row=r + 1, column=c + 1, value=_store(value))
                fmt = sh.formats.get((r, c), sh.formats.get(c))
                if fmt and isinstance(value, (int, Decimal, dt.date)) and not isinstance(value, bool):
                    cell.number_format = fmt
                elif isinstance(value, dt.date):
                    cell.number_format = "yyyy-mm-dd"
                if r in sh.bold_rows:
                    cell.font = bold
        for rng in sh.merged:
            ws.merge_cells(rng)
        for r in sh.hidden_rows:
            ws.row_dimensions[r + 1].hidden = True
        for c, w in sh.widths.items():
            ws.column_dimensions[get_column_letter(c + 1)].width = w
        if sh.hidden:
            ws.sheet_state = "hidden"
    for k, v in (props or {}).items():
        setattr(wb.properties, k, v)
    wb.save(str(path))


def _number(value, decimal: str, thousands: str | None) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return "" if value is None else str(value)
    if isinstance(value, int):
        s = f"{value:,}" if thousands else str(value)
        return s.replace(",", thousands) if thousands else s
    whole, _, frac = format(value, "f").partition(".")
    sign, digits = ("-", whole[1:]) if whole.startswith("-") else ("", whole)
    if thousands:
        digits = f"{int(digits):,}".replace(",", thousands)
    return sign + digits + (decimal + frac if frac else "")


def write_csv(path, header: list[str], rows: list[list], delimiter: str = ",", decimal: str = ".",
              thousands: str | None = None, quote_all: bool = False, bom: bool = False) -> None:
    """CRLF line endings, as spreadsheet exports write them. Numbers follow the habit given; dates and other
    values are written as the caller formatted them."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n",
                   quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL)
    w.writerow(header)
    for row in rows:
        w.writerow([_number(v, decimal, thousands) if isinstance(v, (int, Decimal)) and not isinstance(v, bool)
                    else ("" if v is None else str(v)) for v in row])
    text = ("﻿" if bom else "") + buf.getvalue()
    Path(path).write_bytes(text.encode("utf-8"))


def write_eml(path, *, frm: str, to: str, subject: str, date: dt.datetime, body: str,
              attachments=(), in_reply_to: str | None = None, forward=None) -> str:
    """One email file. `attachments` are (filename, bytes, mime) triples; `forward` is the path of an .eml whose
    message is embedded whole as message/rfc822. Returns the Message-ID. `date` must be timezone-aware."""
    if date.tzinfo is None:
        raise ValueError("email dates carry a zone")
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"], msg["To"], msg["Subject"] = frm, to, subject
    msg["Date"] = email.utils.format_datetime(date)
    domain = frm.rsplit("@", 1)[-1].rstrip(">") if "@" in frm else "mail.example"
    mid = email.utils.make_msgid(domain=domain)
    msg["Message-ID"] = mid
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    if forward is not None:
        inner = email.message_from_bytes(Path(forward).read_bytes(), policy=email.policy.default)
        msg.add_attachment(inner)
    Path(path).write_bytes(msg.as_bytes())
    return mid

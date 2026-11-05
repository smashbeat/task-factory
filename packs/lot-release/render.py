"""lot-release pack: drawing the package's files, each through its own route. Runs inside the pack's generator
image (fonts, Ghostscript, Tesseract, OCRmyPDF, openpyxl).

The workbook, the CSV and the emails are written by the forge's office writers; the label is drawn on the forge's
Pen; the finished-product report and every certificate go through the certificate library and the PDF routes.
Nothing here changes the model: `render_main` checks the truth before and after drawing.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import shutil
import tempfile
from decimal import Decimal as D

from taskfactory.forge import coa_draw
from taskfactory.forge.docforge import Pen, clear_spot, finish, stamp_image, wrap
from taskfactory.forge.office import Sheet, write_csv, write_eml, write_xlsx

from model import *  # noqa: F403  the package model, catalogue and helpers
from model import _slug  # noqa: F401  underscore names do not travel with the star

SCAN_DPI = 200
DATE_FMT = {"iso": "yyyy-mm-dd", "dmy": "dd-mmm-yyyy", "mdy": "mmmm d, yyyy"}
CSV_HEADERS = {
    "sierra": ["Lot", "Expiry", "Pallet", "Cases", "Units per Case", "Loose Units", "Gross kg", "Packed On", "Total Units"],
    "meridian": ["Batch", "Expiry Date", "Pallet No", "Cases", "Units/Case", "Loose", "Gross Weight (kg)", "Date Packed", "Units"],
    "kestrel": ["Batch", "Expiry", "Pallet", "Cases", "Units per case", "Loose", "Packed", "Units"],
}
SHEET_TITLES = {
    "sierra": dict(void="VOID Dispensing", second="Dispensing (2)"),
    "meridian": dict(void="Dispensing Log (SUPERSEDED)", second="Dispensing Log (cont.)"),
    "kestrel": dict(void="Batch Record VOID", second="Batch Record (2)"),
}


def _hy(p, s: str) -> str:
    """The lot as a document other than the workbook prints it: without its hyphen when the package says so."""
    return s.replace("-", "") if p.lot_hyphen and s else s


def _date(p, d) -> str:
    return fmt_date(d, p.style["date_style"])


# ------------------------------------------------------------------ the workbook

def _base_fmt(p, ing, unit: str) -> str:
    f = p.style["wb"]["qty_fmt"][unit]
    if unit == "kg" and ing["pb_unit"] == "g":
        f = "0.000000"
    if unit == "mg":
        f = "#,##0" if ing["pb_unit"] == "kg" else "#,##0.0"
    return f


def _header_rows(p) -> list[list]:
    st = p.style
    return [[st["lot_word"], p.lot], ["Product", p.product], ["Client", p.client], ["Dosage form", p.form],
            ["Serving", p.serving_text], ["Servings per unit", p.servings], ["Batch size (units)", p.batch_size],
            ["Manufactured on", p.manufactured_on], ["Yield (units)", p.yield_units], ["Status", "Complete"]]


def _columns(p, uniform):
    """Header cells and the indices of the required and dispensed columns, per style."""
    key = p.style_key
    if key == "sierra":
        return ["Code", "Material", "Required", "Unit", "Dispensed", "Unit", "Supplier", "Supplier Lot", "Note"], 2, 4
    if key == "meridian":
        if uniform:
            return ["Code", "Material", f"Required ({uniform})", f"Dispensed ({uniform})", "Supplier", "Supplier Lot", "Status"], 2, 3
        return ["Code", "Material", "Required", "Dispensed", "Unit", "Supplier", "Supplier Lot", "Status"], 2, 3
    return ["Code", "Material", "Required", "Dispensed", "Unit", "Supplier", "Supplier lot", "Checked"], 2, 3


def _table_row(p, ing, r, uniform) -> list:
    required = convert_mass(ing["per_batch"], ing["pb_unit"], r["printed_unit"])
    disp = r["text"] if r["text"] is not None else r["stored"]
    mark = "VOID" if r["void"] else ""
    sup = SUPPLIERS[r["supplier"]]["name"]
    key = p.style_key
    if key == "sierra":
        return [ing["code"], ing["material"][0], required, r["printed_unit"], disp, r["printed_unit"], sup, r["lot"], mark]
    if key == "meridian":
        row = [ing["code"], ing["material"][0], required, disp, sup, r["lot"], mark or "Dispensed"]
        if not uniform:
            row.insert(4, r["printed_unit"])
        return row
    return [ing["code"], ing["material"][0], required, disp, r["printed_unit"], sup, r["lot"], mark or "Yes"]


def _table_sheet(p, title, pairs, uniform, hidden=False, banner=None, with_block=False, totals=False) -> Sheet:
    st, key = p.style, p.style_key
    rows, formats, hidden_rows, bold, merged = [], {}, [], [], []
    header, req_col, disp_col = _columns(p, uniform)
    if banner:
        rows.append([banner] + [None] * (len(header) - 1))
        bold.append(0)
    if with_block:
        for lab, val in _header_rows(p):
            if val == p.manufactured_on:
                formats[(len(rows), 1)] = DATE_FMT[st["date_style"]]
            rows.append([lab, val])
        rows.append([])
        if uniform:
            rows.append([f"All quantities in {uniform}"])
    bold.append(len(rows))
    rows.append(header)
    shown_total, req_total = D(0), D(0)
    for ing, r in pairs:
        ri = len(rows)
        rows.append(_table_row(p, ing, r, uniform))
        formats[(ri, req_col)] = _base_fmt(p, ing, r["printed_unit"])
        formats[(ri, disp_col)] = r["fmt"]
        if r["hidden"]:
            hidden_rows.append(ri)
        if not r["void"]:
            shown_total += shown(r["stored"], r["fmt"]) if r["text"] is None else D(r["text"].replace(",", ""))
            req_total += convert_mass(ing["per_batch"], ing["pb_unit"], r["printed_unit"])
    if totals and uniform and pairs:
        if p.workbook["totals_lie"] == "workbook":
            shown_total += D(7) * D(1).scaleb(-(len(pairs[0][1]["fmt"].split(".")[1]) if "." in pairs[0][1]["fmt"] else 0))
        row = [None] * len(header)
        row[0], row[req_col], row[disp_col] = "Total", req_total, shown_total
        formats[(len(rows), req_col)] = formats[(len(rows), disp_col)] = pairs[0][1]["fmt"]
        bold.append(len(rows))
        rows.append(row)
    widths = {1: 30, header.index("Supplier"): 30} if "Supplier" in header else {1: 30}
    return Sheet(title, rows, formats=formats, merged=merged, hidden_rows=hidden_rows, hidden=hidden, widths=widths, bold_rows=bold)


def workbook_sheets(p) -> list[Sheet]:
    st, key, wb = p.style, p.style_key, p.workbook
    pairs = [(ing, r) for ing in p.ingredients for r in ing["rows"]]
    units = {r["printed_unit"] for _, r in pairs}
    uniform = next(iter(units)) if len(units) == 1 else None
    by_code = {ing["code"]: ing for ing in p.ingredients}
    titles = SHEET_TITLES[key]
    sheets = []
    if wb["void_sheet"] is not None:
        vpairs = [(by_code[code], r) for code, r in wb["void_sheet"]["rows"]]
        sheets.append(_table_sheet(p, titles["void"], vpairs, uniform, hidden=wb["void_sheet"]["hidden"], banner="VOID",
                                   with_block=key == "kestrel"))
    first = [(ing, r) for ing, r in pairs if r["sheet"] == 0]
    second = [(ing, r) for ing, r in pairs if r["sheet"] == 1]
    if key == "kestrel":
        sheets.append(_table_sheet(p, st["wb"]["sheets"][0], first, uniform, with_block=True, totals=wb["totals"] and not second))
    else:
        formats = {}
        rows = []
        for lab, val in _header_rows(p):
            if val == p.manufactured_on:
                formats[(len(rows), 1)] = DATE_FMT[st["date_style"]]
            rows.append([lab, val])
        sheets.append(Sheet(st["wb"]["sheets"][0], rows, formats=formats, widths={0: 22, 1: 34}, bold_rows=[]))
        sheets.append(_table_sheet(p, st["wb"]["sheets"][1], first, uniform, totals=wb["totals"] and not second))
    if second:
        sheets.append(_table_sheet(p, titles["second"], second, uniform, totals=wb["totals"]))
    return sheets


# ------------------------------------------------------------------ the packing record

def write_packing(p, path) -> None:
    st, pk, key = p.style, p.packing, p.style_key
    lot, exp, packed = _hy(p, pk["lot"]), _date(p, pk["expiry"]), _date(p, p.packed_on)
    gross = st["csv"]["gross"]
    rows = []
    for l in pk["lines"]:
        units = l["cases"] * l["upc"] + l["loose"]
        row = [lot, exp, l["pallet"], l["cases"], l["upc"], l["loose"]] + ([l["gross"]] if gross else []) + [packed, units]
        rows.append(row)
    if pk["total"]:
        row = [st["csv"]["total_label"], "", "", sum(l["cases"] for l in pk["lines"]), "", sum(l["loose"] for l in pk["lines"])]
        row += [sum((l["gross"] for l in pk["lines"]), D(0))] if gross else []
        row += ["", pk["total_value"]]
        rows.append(row)
    semi = pk["habit"] == "semicolon"
    write_csv(path, CSV_HEADERS[key], rows, delimiter=";" if semi else ",", decimal="," if semi else ".",
              thousands="." if semi else ("," if key == "meridian" else None), quote_all=key == "meridian", bom=key == "meridian")


# ------------------------------------------------------------------ the label proof

def draw_label(p, path, rnd) -> str:
    st, lab = p.style, p.label
    td = tempfile.mkdtemp()
    base = os.path.join(td, "label.pdf")
    pen = Pen(base, st)
    x0, pw = 54, 300
    pen.text(x0, p.client.upper(), 20, bold=True, y=80)
    pen.text(x0, p.product, 16, bold=True, y=104)
    pen.text(x0, f"{p.form} | Dietary Supplement | {p.servings} {p.form.lower()}", 10, y=122)
    y = 160
    pen.line(x0, x0 + pw, y=y, width=1.5)
    pen.text(x0 + 4, "Supplement Facts", 15, bold=True, y=y + 22)
    pen.text(x0 + 4, f"Serving Size: {p.serving_text}", 9.5, y=y + 40)
    pen.text(x0 + 4, f"Servings Per Container: {p.servings}", 9.5, y=y + 52)
    pen.line(x0, x0 + pw, y=y + 58, width=3)
    pen.text(x0 + 4, "Amount Per Serving", 9, bold=True, y=y + 72)
    pen.text(x0 + pw - 4, "% DV", 9, bold=True, y=y + 72, align="right")
    pen.line(x0, x0 + pw, y=y + 76, width=0.6)
    yy = y + 90
    for a in lab["amounts"]:
        pen.text(x0 + 4, a["label_name"], 9.5, y=yy)
        pen.text(x0 + pw - 60, f"{fmt(a['amount'])} {a['unit']}", 9.5, y=yy, align="right")
        pen.text(x0 + pw - 4, "*", 9.5, y=yy, align="right")
        pen.line(x0, x0 + pw, y=yy + 4, width=0.4)
        yy += 14
    pen.line(x0, x0 + pw, y=yy + 2, width=3)
    pen.text(x0 + 4, "* Daily Value not established.", 8, y=yy + 14)
    yy += 32
    for line in wrap(pen, "Other ingredients: hypromellose (capsule), rice flour, magnesium stearate, silicon dioxide.", pw + 120, 9):
        pen.text(x0, line, 9, y=yy)
        yy += 12
    if lab["allergens"]:
        pen.text(x0, "Contains: " + ", ".join(lab["allergens"]) + ".", 9.5, bold=True, y=yy + 4)
        yy += 16
    # the lot and expiry box at the right
    bx, by, bw, bh = pen.w - 54 - 200, 160, 200, 48
    pen.line(bx, bx + bw, y=by); pen.line(bx, bx + bw, y=by + bh)
    pen.vline(bx, by, by + bh); pen.vline(bx + bw, by, by + bh)
    pen.text(bx + 8, f"LOT {_hy(p, lab['lot'])}", 10.5, bold=True, y=by + 19)
    pen.text(bx + 8, f"EXP {_date(p, lab['expiry'])}", 10.5, bold=True, y=by + 38)
    if lab["revisions"]:
        ry = max(yy + 24, 420)
        pen.text(x0, "Artwork revisions", 10, bold=True, y=ry)
        cols = [x0, x0 + 40, x0 + 230, x0 + 380]
        for cx, head in zip(cols, ["Rev", "Field", "Value", "Date"]):
            pen.text(cx, head, 9, bold=True, y=ry + 16)
        pen.line(x0, x0 + 440, y=ry + 20)
        names = {a["code"]: a["label_name"] for a in lab["amounts"]}
        names.update({ing["code"]: ing["label_name"] for ing in p.ingredients})
        for i, rev in enumerate(sorted(lab["revisions"], key=lambda r: r["rev"])):
            ry2 = ry + 34 + 14 * i
            field = {"lot": "Lot", "expiry": "Expiry"}.get(rev["field"], names.get(rev["field"], rev["field"]))
            v = rev["value"]
            value = _hy(p, v) if rev["field"] == "lot" else _date(p, v) if rev["field"] == "expiry" else f"{fmt(v[0])} {v[1]}"
            when = p.manufactured_on - dt.timedelta(days=30 - 9 * i)
            for cx, cell in zip(cols, [str(rev["rev"]), field, value, _date(p, when)]):
                pen.text(cx, cell, 9, y=ry2)
    pen.text(x0, f"Manufactured for {p.client} by {st['name']}", 8, y=pen.h - 52)
    pen.text(x0, st["address"], 8, y=pen.h - 40)
    pen.save()
    route = "outlined" if lab["outlined"] else "digital"
    finish(route, base, path, rnd, st["meta"], st["size"], dpi=SCAN_DPI)
    shutil.rmtree(td)
    return route


# ------------------------------------------------------------------ reports, certificates, emails

def write_report(p, path, rnd) -> str:
    c = copy.deepcopy(p.fp["cert"])
    c.lots[0]["lot_number"] = _hy(p, p.fp["lot"])
    return coa_draw.produce(c, path, rnd, dpi=SCAN_DPI)


def write_cert(p, doc, path, rnd) -> str:
    pre = None
    if doc["void"]:
        td = tempfile.mkdtemp()
        img = stamp_image("VOID", rnd)
        sw, sh = img.width * 0.5, img.height * 0.5
        dry = coa_draw.render(doc["cert"], os.path.join(td, "dry.pdf"), {})
        sx, sy = clear_spot(dry.boxes, dry.w, dry.h, sw, sh)
        shutil.rmtree(td)

        def pre(pen, img=img, sx=sx, sy=sy, sw=sw, sh=sh):
            if pen.page_no == 1:
                pen.image(img, sx, sy, sw, sh)
    return coa_draw.produce(doc["cert"], path, rnd, pre=pre, dpi=SCAN_DPI)


def write_emails(p, out_dir, cert_bytes, td) -> None:
    ids: dict[int, str] = {}

    def attachments(e):
        out = []
        for i in e["attachments"]:
            d = p.certs[i]
            out.append((f"CoA_{_slug(d['cert'].material[0])}_{d['lots'][0]}.pdf", cert_bytes[i], "application/pdf"))
        return out

    def write_one(idx, path):
        e = p.emails[idx]
        kw = dict(frm=e["frm"], to=e["to"], subject=e["subject"], date=e["date"], body=e["body"])
        if e["forward_of"] is not None:
            inner = e["forward_of"]
            if inner not in ids:
                ids[inner] = write_one(inner, os.path.join(td, f"inner{inner}.eml"))
            kw["forward"] = os.path.join(td, f"inner{inner}.eml")
        else:
            kw["attachments"] = attachments(e)
            if e["reply_of"] is not None:
                orig = e["reply_of"]
                if orig not in ids:
                    name = p.emails[orig]["name"]
                    ids[orig] = write_one(orig, os.path.join(out_dir, name) if name else os.path.join(td, f"inner{orig}.eml"))
                kw["in_reply_to"] = ids[orig]
        return write_eml(path, **kw)

    for idx, e in enumerate(p.emails):
        if e["embedded"] or idx in ids:
            continue
        ids[idx] = write_one(idx, os.path.join(out_dir, e["name"]))


def render_item(p, path, rng) -> str:
    """Write the package folder. Returns the production note for the manifest."""
    os.makedirs(path, exist_ok=True)
    td = tempfile.mkdtemp()
    notes = [p.route]
    write_xlsx(os.path.join(path, p.workbook["name"]), workbook_sheets(p),
               props={"creator": p.style["wb"]["creator"], "title": f"Batch record {p.lot}"})
    write_packing(p, os.path.join(path, p.packing["name"]))
    notes.append("label " + draw_label(p, os.path.join(path, p.label["name"]), rng))
    if p.fp["present"]:
        notes.append("report " + write_report(p, os.path.join(path, p.fp["name"]), rng))
    cert_bytes = {}
    for i, doc in enumerate(p.certs):
        tmp = os.path.join(td, f"c{i}.pdf")
        note = write_cert(p, doc, tmp, rng)
        if doc["email"] is None:
            shutil.copy(tmp, os.path.join(path, doc["name"]))
        else:
            with open(tmp, "rb") as f:
                cert_bytes[i] = f.read()
        notes.append(f"cert {i} ({doc['supplier']}, {'void, ' if doc['void'] else ''}{doc['route']}): {note}")
    write_emails(p, path, cert_bytes, td)
    shutil.rmtree(td)
    return "; ".join(notes + p.notes)

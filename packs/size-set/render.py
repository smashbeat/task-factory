"""size-set domain pack: drawing the measurement report in its vendor's template and choosing its production
route. Runs inside the generator image (fonts, Ghostscript, Tesseract, OCRmyPDF). `render_item(item, path, rng)`
continues the item's own random stream after apply_features. The forge (pen, routes, overlays) is
taskfactory.forge.docforge."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
from fractions import Fraction as F

import pikepdf
from PIL import Image, ImageDraw, ImageFont

from taskfactory.forge.docforge import (A4, LETTER, STAMP_FONT, Pen, finish, freetext_correction, set_meta,
                                        wrap)

from model import *  # noqa: F403  the report model, catalogue and helpers

LETTER_LANDSCAPE = (792.0, 612.0)
UNIT_WORD = {"in": "inches", "cm": "centimetres"}


# ------------------------------------------------------------------ what the page prints

class Page:
    """Strings for one report, in the printed unit and notation. Keys are (code, size, piece)."""

    def __init__(self, c: Report, unit=None, prec=None):
        self.c = c
        self.force = c.in_force()
        self.unit = unit or c.printed_unit
        self.prec = prec or (c.printed_prec if self.unit == c.printed_unit else (F(1, 10) if self.unit == "cm" else F(1, 8)))
        self.notation = c.notation if self.unit == "in" else "frac"

    def q(self, v: F, signed=False) -> str:
        v = round_to(v, self.prec)
        places = 2 if (self.notation == "decimal" and self.unit == "in") else None
        return fmt_qty(v, self.unit, signed=signed, notation=self.notation, places=places)

    def value(self, key) -> str:
        v = self.c.printed.get(key)
        if key in self.c.corrections:
            v = self.c.corrections[key]["wrong"]         # the page prints the wrong value; the correction covers it
        return "" if v is None else self.q(v)

    def spec_value(self, code, size) -> str:
        v = self.c.column_lies["spec"].get((code, size), self.force[(code, size)])
        v = v * (2 if code in self.c.full_circ else 1)
        return self.q(convert(v, self.c.unit, self.unit))

    def diff(self, key) -> str:
        if self.c.printed.get(key) is None:
            return ""
        if key in self.c.column_lies["diff"]:
            d = convert(self.c.column_lies["diff"][key], self.c.unit, self.unit)
        else:
            spec = self.force[key[:2]] * (2 if key[0] in self.c.full_circ else 1)
            d = self.c.printed[key] - convert(spec, self.c.unit, self.unit)
        return self.q(d, signed=True)

    def within(self, key) -> bool | None:
        if self.c.printed.get(key) is None:
            return None
        if key in self.c.column_lies["status"]:
            return self.c.column_lies["status"][key]
        p = self.c.point(key[0])
        m = self.c.house_value(key, self.c.printed[key], self.c.printed_unit)
        s = self.force[key[:2]]
        return s - p["tol_minus"] <= m <= s + p["tol_plus"]

    def tol(self, p, sign) -> str:
        return self.q(convert(p["tol_plus" if sign > 0 else "tol_minus"], self.c.unit, self.unit))

    def name(self, p) -> str:
        n = p["names"][2] if self.c.long_names else p["names"][0]
        if p["code"] in self.c.full_circ and self.c.house["layout"] in ("subcols", "columns"):
            n += " (full circ.)"
        return n


# ------------------------------------------------------------------ drawing

def draw_header(pen, c: Report, pg: Page, kind="main", date=None):
    """kind: main, continued, remeasure. Leaves pen.y under the header."""
    h, k = c.house, c.house_key
    ds = h["date_style"]
    title = h["title"]
    if kind == "continued":
        title += " (continued)"
    elif kind == "remeasure":
        title += ", re-measurement"
    unit_line = f"All measurements in {UNIT_WORD[pg.unit]}" if "unit_note" in c.features else None
    if k == "yongsheng":
        pen.text(40, h["name"], 13, bold=True); pen.y += 12
        pen.text(40, h["address"], 8); pen.y += 16
        pen.text(pen.w / 2, title, 12, bold=True, align="center"); pen.y += 6
        pen.line(40, pen.w - 40, width=1.0); pen.y += 14
        x = 40
        for lab, val in (("Style No.", c.style), ("Description", c.garment), ("Stage", c.stage),
                         ("Measured on", fmt_date(date or c.measured_on, ds))):
            pen.text(x, lab + ":", 8.5, bold=True)
            pen.text(x + pen.width(lab + ":", 8.5, True) + 4, val, 8.5)
            x += 195
        pen.y += 13
        pen.text(40, unit_line or f"Unit: {pg.unit}", 8.5, bold=True)
        pen.y += 16
    elif k == "plm":
        pen.text(54, h["name"], 12, bold=True); pen.y += 12
        pen.text(54, h["address"], 8); pen.y += 18
        pen.text(54, title, 13, bold=True); pen.y += 8
        pen.line(54, pen.w - 54, width=0.6); pen.y += 16
        for lab, val in (("Style", c.style), ("Product", c.garment), ("Sample stage", c.stage),
                         ("Date measured", fmt_date(date or c.measured_on, ds)),
                         ("Measurements", unit_line or UNIT_WORD[pg.unit])):
            pen.text(54, lab + ":", 9, bold=True); pen.text(170, val, 9); pen.y += 13
        pen.y += 6
    elif k == "inspect":
        pen.text(pen.w / 2, h["name"].upper(), 14, bold=True, align="center"); pen.y += 13
        pen.text(pen.w / 2, h["address"], 8.5, align="center"); pen.y += 20
        pen.text(pen.w / 2, title, 12, bold=True, align="center"); pen.y += 4
        tw = pen.width(title, 12, True)
        pen.line(pen.w / 2 - tw / 2, pen.w / 2 + tw / 2, width=0.8); pen.y += 18
        for lab, val in (("Style reference", c.style), ("Article", c.garment), ("Sample type", c.stage),
                         ("Inspection date", fmt_date(date or c.measured_on, ds))):
            pen.text(54, lab, 9.5, bold=True); pen.text(190, val, 9.5); pen.y += 13
        pen.text(54, unit_line or f"Measurements are stated in {UNIT_WORD[pg.unit]}.", 8.5)
        pen.y += 18
    else:   # tablet
        pen.text(54, h["name"], 12, bold=True); pen.y += 12
        pen.text(54, h["address"], 8); pen.y += 16
        pen.text(54, title, 11, bold=True); pen.y += 14
        for lab, val in (("Style", c.style), ("Item", c.garment), ("Stage", c.stage),
                         ("Session", fmt_date(date or c.measured_on, ds))):
            pen.text(54, lab, 9, bold=True); pen.text(130, val, 9); pen.y += 12
        pen.text(54, unit_line or f"Units: {pg.unit}", 9, bold=True)
        pen.y += 16


def grid(pen, cols, rows, head_rows, bottom, on_new_page, size=8.5, lh=11, x0=54, scramble=False, split_at=None,
         cells=None, stamps=None):
    """cols: widths. head_rows: rows of (text, span). rows: lists of (text, key): key None or a (code, size,
    piece) whose box goes to `cells` and whose correction stamp, if any, is drawn over it. Breaks at `bottom`."""
    total = sum(cols)

    def header():
        for hr in head_rows:
            x, i = x0, 0
            for text, span in hr:
                w = sum(cols[i:i + span])
                if text:
                    pen.text(x + w / 2, text, size, bold=True, align="center")
                i += span
                x += w
            pen.y += lh
        pen.y -= 3
        pen.line(x0, x0 + total, width=0.8)
        pen.y += lh

    header()
    for ri, row in enumerate(rows):
        pieces, depth = [], 1
        for (text, key), w in zip(row, cols):
            lines = wrap(pen, text, w, size) if text else [""]
            depth = max(depth, len(lines))
            pieces.append(lines)
        if pen.y + depth * lh > bottom or (split_at is not None and ri == split_at):
            on_new_page()
            header()
        x = x0
        placements = []
        for (text, key), w, lines in zip(row, cols, pieces):
            for k, line in enumerate(lines):
                placements.append((x + 3, pen.y + k * lh, line, key if k == 0 else None))
            x += w
        if scramble:
            placements = list(reversed(placements))
        for px, py, line, key in placements:
            if line:
                pen.text(px, line, size, y=py)
            if key is not None:
                box = (pen.page_no, px - 2, py - size - 1, px + max(pen.width(line, size), 10) + 2, py + 3)
                if cells is not None:
                    cells[key] = box
                if stamps and key in stamps:
                    img = stamps[key]
                    sh = size + 7
                    sw = img.width * sh / img.height
                    pen.image(img, px - 4, py - size - 3, sw, sh)
        pen.y += (depth - 1) * lh + 3
        pen.line(x0, x0 + total, width=0.25)
        pen.y += lh


def code_col(c, width=34):
    return [] if c.by_name else [width]


def code_cell(c, p):
    return [] if c.by_name else [(p["code"], None)]


def draw_yongsheng(pen, c, pg, v, cells, sizes=None):
    """Points as rows; per size and piece the sub-columns Spec, Act, Diff. Pages of at most five groups."""
    groups = [(s, k) for s in (sizes or c.sizes_measured) for k in range(1, c.pieces[s] + 1)]
    bottom = pen.h - 50
    chunks = [groups[i:i + 5] for i in range(0, len(groups), 5)]
    for ci, chunk in enumerate(chunks):
        if ci:
            v["new_page"]()
        cols = code_col(c, 36) + [150 if c.long_names else 140, 48]
        head1 = ([("Code", 1)] if not c.by_name else []) + [("Point of measure", 1), ("Tol.", 1)]
        head2 = ([("", 1)] if not c.by_name else []) + [("", 1), ("+/-", 1)]
        for s, k in chunk:
            head1.append((s if c.pieces[s] == 1 else f"{s} {c.house['piece_word'].format(n=k)}", 3))
            head2 += [("Spec", 1), ("Act", 1), ("Diff", 1)]
            cols += [34, 34, 34]
        rows = []
        for p in c.spec_points:
            tol = pg.tol(p, 1) if p["tol_plus"] == p["tol_minus"] else f"+{pg.tol(p, 1)}/-{pg.tol(p, -1)}"
            r = code_cell(c, p) + [(pg.name(p), None), (tol, None)]
            for s, k in chunk:
                key = (p["code"], s, k)
                r += [(pg.spec_value(p["code"], s), None), (pg.value(key), key), (pg.diff(key), None)]
            rows.append(r)
        for code, name, vals in c.extra:
            r = ([(code, None)] if not c.by_name else []) + [(name, None), ("", None)]
            for s, k in chunk:
                r += [("", None), (pg.q(vals[(s, k)]), None), ("", None)]
            rows.append(r)
        grid(pen, cols, rows, [head1, head2], bottom, v["new_page"], size=7.5, lh=10.5, x0=40,
             scramble=v.get("scramble"), split_at=v.get("split_at") if ci == 0 else None, cells=cells,
             stamps=v.get("stamps"))


def draw_plm(pen, c, pg, v, cells, sizes=None):
    """Points as rows with code, name, Tol+, Tol-; one column of actuals per size and piece."""
    groups = [(s, k) for s in (sizes or c.sizes_measured) for k in range(1, c.pieces[s] + 1)]
    bottom = pen.h - 60
    cols = code_col(c) + [118 if len(groups) > 6 else 150, 32, 32]
    head = ([("Code", 1)] if not c.by_name else []) + [("Point of measure", 1), ("Tol +", 1), ("Tol -", 1)]
    fixed = sum(cols)
    for s, k in groups:
        head.append((s if c.pieces[s] == 1 else c.house["piece_word"].format(size=s, n=k), 1))
        cols.append(max(28, int((504 - fixed) / len(groups))))
    rows = []
    for p in c.spec_points:
        r = code_cell(c, p) + [(pg.name(p), None), (pg.tol(p, 1), None), (pg.tol(p, -1), None)]
        for s, k in groups:
            key = (p["code"], s, k)
            r.append((pg.value(key), key))
        rows.append(r)
    for code, name, vals in c.extra:
        r = ([(code, None)] if not c.by_name else []) + [(name, None), ("", None), ("", None)]
        r += [(pg.q(vals[(s, k)]), None) for s, k in groups]
        rows.append(r)
    grid(pen, cols, rows, [head], bottom, v["new_page"], size=8, lh=11, x0=54,
         scramble=v.get("scramble"), split_at=v.get("split_at"), cells=cells, stamps=v.get("stamps"))


def draw_inspect(pen, c, pg, v, cells, sizes=None):
    """One block per size: points as rows, pieces as columns, a result column."""
    bottom = pen.h - 60
    for si, s in enumerate(sizes or c.sizes_measured):
        n = c.pieces[s]
        if si and pen.y > bottom - 160:
            v["new_page"]()
        pen.text(54, f"Size {s}" + (f", {n} samples" if n > 1 else ""), 10, bold=True)
        pen.y += 14
        cols = code_col(c) + [150 if c.long_names else 170, 52, 48] + [56] * n + [52]
        head = ([("Code", 1)] if not c.by_name else []) + [("Point of measure", 1), ("Spec", 1), ("Tol.", 1)]
        head += [(c.house["piece_word"].format(letter="AB"[k]), 1) for k in range(n)] + [("Result", 1)]
        rows = []
        for p in c.spec_points:
            tol = f"±{pg.tol(p, 1)}" if p["tol_plus"] == p["tol_minus"] else f"+{pg.tol(p, 1)} / -{pg.tol(p, -1)}"
            r = code_cell(c, p) + [(pg.name(p), None), (pg.spec_value(p["code"], s), None), (tol, None)]
            res = []
            for k in range(1, n + 1):
                key = (p["code"], s, k)
                r.append((pg.value(key), key))
                res.append(pg.within(key))
            r.append(("" if all(x is None for x in res) else ("OK" if all(x is not False for x in res) else "OUT"), None))
            rows.append(r)
        for code, name, vals in c.extra:
            r = ([(code, None)] if not c.by_name else []) + [(name, None), ("", None), ("", None)]
            r += [(pg.q(vals[(s, k)]), None) for k in range(1, n + 1)] + [("", None)]
            rows.append(r)
        grid(pen, cols, rows, [head], bottom, v["new_page"], size=8.5, lh=11.5, x0=54,
             scramble=v.get("scramble"), split_at=v.get("split_at") if si == 0 else None, cells=cells,
             stamps=v.get("stamps"))
        pen.y += 10


def draw_tablet(pen, c, pg, v, cells, sizes=None):
    """One page per size and piece: rows of spec, measured, deviation and status."""
    bottom = pen.h - 60
    first = True
    for s in (sizes or c.sizes_measured):
        for k in range(1, c.pieces[s] + 1):
            if not first:
                v["new_page"]()
            pen.text(54, f"Size {s}, {c.house['piece_word'].format(n=k)}", 10.5, bold=True)
            pen.y += 15
            cols = code_col(c) + [160 if c.long_names else 190, 60, 60, 60, 50]
            head = ([("Code", 1)] if not c.by_name else []) + [("Point", 1), ("Spec", 1), ("Measured", 1), ("Deviation", 1), ("Status", 1)]
            rows = []
            for p in c.spec_points:
                key = (p["code"], s, k)
                w = pg.within(key)
                r = code_cell(c, p) + [(pg.name(p), None), (pg.spec_value(p["code"], s), None), (pg.value(key), key),
                                       (pg.diff(key), None), ("" if w is None else ("PASS" if w else "FAIL"), None)]
                rows.append(r)
            for code, name, vals in c.extra:
                r = ([(code, None)] if not c.by_name else []) + [(name, None), ("", None), (pg.q(vals[(s, k)]), None), ("", None), ("", None)]
                rows.append(r)
            grid(pen, cols, rows, [head], bottom, v["new_page"], size=9, lh=12, x0=54,
                 scramble=v.get("scramble"), split_at=v.get("split_at") if first else None, cells=cells,
                 stamps=v.get("stamps"))
            first = False


DRAW = {"yongsheng": draw_yongsheng, "plm": draw_plm, "inspect": draw_inspect, "tablet": draw_tablet}


def draw_notes(pen, c, pg):
    if c.full_circ and c.house["layout"] in ("blocks", "pages"):
        names = [pg.name(p) for p in c.spec_points if p["code"] in c.full_circ]
        pen.y += 4
        pen.text(54 if c.house_key != "yongsheng" else 40,
                 f"Note: {' and '.join(names)} measured around the full circumference.", 8.5)
        pen.y += 11


def draw_remeasure_block(pen, c, pg, v, r):
    h = c.house
    x0 = 40 if c.house_key == "yongsheng" else 54
    if pen.y > pen.h - 150:
        v["new_page"]()
    bp = Page(c, unit=r["unit"])
    pen.y += 8
    pen.text(x0, h["remeasure_word"].format(date=fmt_date(r["date"], h["date_style"])), 9.5, bold=True)
    pen.y += 12
    if r["unit"] != pg.unit:
        pen.text(x0, f"Values in {UNIT_WORD[r['unit']]}.", 8.5)
        pen.y += 12
    cols = code_col(c) + [150, 50, 60, 60]
    head = ([("Code", 1)] if not c.by_name else []) + [("Point of measure", 1), ("Size", 1), ("Piece", 1), ("Value", 1)]
    order = [p["code"] for p in c.spec_points]
    rows = []
    for key, val in sorted(r["values"].items(), key=lambda kv: (order.index(kv[0][0]), c.sizes.index(kv[0][1]), kv[0][2])):
        p = c.point(key[0])
        rows.append(code_cell(c, p) + [(pg.name(p), None), (key[1], None), (str(key[2]), None), (bp.q(val), None)])
    grid(pen, cols, rows, [head], pen.h - 50, v["new_page"], size=8.5, lh=11, x0=x0)


def draw_footer(pen, c):
    pen.y += 10
    x0 = 40 if c.house_key == "yongsheng" else 54
    signer = {"yongsheng": "Measured by: QC Dept.        Checked by: Merchandiser",
              "plm": "Measured by the vendor's QA. Returned through the PLM supplier portal.",
              "inspect": "Inspector: K. W. Chan        Reviewed: Quality Manager",
              "tablet": "Exported from QC Measure. Session closed by the operator."}[c.house_key]
    pen.text(x0, signer, 8.5)


def render(c: Report, path, variant=None):
    """Draw the report with reportlab. variant: drawing switches for routes and overlays. Returns the pen:
    `cells` maps each (code, size, piece) to the box of its printed value, `page_sizes` each page to its size."""
    v = dict(variant or {})
    h = c.house
    pg = Page(c)
    pen = Pen(path, h, v.get("size"))
    pen.cells, pen.page_sizes = {}, {1: tuple(pen.size)}
    draw = DRAW[c.house_key]
    state = {"page": pg}

    def new_page(kind="continued", date=None):
        pen.new_page(v.get("cont_size"))
        pen.page_sizes[pen.page_no] = tuple(pen.size)
        if v.get("pre"):
            v["pre"](pen)
        draw_header(pen, c, state["page"], kind, date)

    v["new_page"] = new_page
    if v.get("pre"):
        v["pre"](pen)
    draw_header(pen, c, pg)
    draw(pen, c, pg, v, pen.cells)
    draw_notes(pen, c, pg)
    for r in c.remeasurements:
        if r["kind"] == "block":
            draw_remeasure_block(pen, c, pg, v, r)
    draw_footer(pen, c)
    for r in c.remeasurements:
        if r["kind"] == "page":
            rp = Page(c, unit=r["unit"])
            state["page"] = rp
            new_page("remeasure", r["date"])
            pen.text(54 if c.house_key != "yongsheng" else 40,
                     h["remeasure_word"].format(date=fmt_date(r["date"], h["date_style"])) + f" Size {r['size']}.",
                     9.5, bold=True)
            pen.y += 18
            # the page restates the size with the re-measured values in place, in the block's unit
            saved_printed, saved_corr = c.printed, c.corrections
            c.printed = {**c.printed, **r["values"]}
            c.corrections = {}
            sub = {k: vv for k, vv in v.items() if k not in ("split_at", "scramble", "stamps")}
            draw(pen, c, rp, sub, {}, sizes=[r["size"]])
            c.printed, c.corrections = saved_printed, saved_corr
            draw_footer(pen, c)
            state["page"] = pg
    if v.get("post"):
        v["post"](pen)
    pen.save()
    return pen


# ------------------------------------------------------------------ overlays and routes

def correction_stamp(text, rnd):
    """A red boxed correction with an opaque white fill: covers the printed value it replaces."""
    font = ImageFont.truetype(STAMP_FONT, 40)
    tw = int(font.getlength(text)) + 36
    im = Image.new("RGBA", (tw, 64), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([2, 2, tw - 3, 61], outline=(160, 20, 30, 255), width=4)
    d.text((18, 8), text, fill=(160, 20, 30, 255), font=font)
    return im.rotate(rnd.uniform(-3, 3), expand=True, resample=Image.BICUBIC, fillcolor=(255, 255, 255, 0))


def build_form(c: Report, path, mismatch):
    """A fillable form (reportlab AcroForm): one text field per measured value. One size."""
    h = c.house
    pg = Page(c)
    if pg.notation == "glyph":
        pg.notation = "frac"          # a form field is set in a standard font, which has no fraction glyphs
    size = LETTER if h["size"] in (LETTER, A4) else A4
    pen = Pen(path, h, size)
    draw_header(pen, c, pg)
    form = pen.c.acroForm
    s = c.sizes_measured[0]
    n = c.pieces[s]
    x0 = 54
    pen.text(x0, f"Size {s}", 10, bold=True); pen.y += 14
    name_x = 37 if not c.by_name else 3
    heads = ([("Code", 0)] if not c.by_name else []) + [("Point of measure", name_x - 3), ("Spec", 214), ("Tol +", 258), ("Tol -", 294)]
    for k in range(n):
        heads.append((f"Measured {k + 1}" if n > 1 else "Measured", 334 + k * 80))
    for head, dx in heads:
        pen.text(x0 + dx + 3, head, 9, bold=True)
    pen.y += 5; pen.line(x0, x0 + 500, width=0.8); pen.y += 14

    def field(name, value, k):
        form.textfield(name=name, value=value, x=x0 + 334 + (k - 1) * 80, y=pen.h - pen.y - 4, width=70, height=14,
                       fontName="Helvetica", fontSize=9, borderWidth=0.4, borderColor=None, fillColor=None,
                       textColor=None, forceBorder=False)

    for p in c.spec_points:
        if not c.by_name:
            pen.text(x0 + 3, p["code"], 9)
        pen.text(x0 + name_x, pg.name(p)[:34], 9)
        pen.text(x0 + 217, pg.spec_value(p["code"], s), 9)
        pen.text(x0 + 261, pg.tol(p, 1), 9)
        pen.text(x0 + 297, pg.tol(p, -1), 9)
        for k in range(1, n + 1):
            field(f"m_{p['code']}_{k}", pg.value((p["code"], s, k)), k)
        pen.y += 18
    for code, name, vals in c.extra:
        if not c.by_name:
            pen.text(x0 + 3, code, 9)
        pen.text(x0 + name_x, name, 9)
        for k in range(1, n + 1):
            field(f"m_{code}_{k}", pg.q(vals[(s, k)]), k)
        pen.y += 18
    draw_notes(pen, c, pg)
    draw_footer(pen, c)
    pen.save()
    if mismatch:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            for annot in pdf.pages[0].get("/Annots", []):
                name = str(annot.get("/T", ""))
                val = str(annot.get("/V", ""))
                if name.startswith("m_") and val:
                    try:
                        q = parse_qty(val)
                    except (ValueError, ZeroDivisionError):
                        continue
                    annot.V = pikepdf.String(fmt_qty(q + F(3, 2), c.printed_unit))
            if "/AcroForm" in pdf.Root:
                pdf.Root.AcroForm.NeedAppearances = False
            pdf.save(path)


def produce(c: Report, path, rnd):
    """Render the report through its production route. Returns notes for the manifest."""
    route, h = c.route, c.house
    td = tempfile.mkdtemp()
    base = os.path.join(td, "base.pdf")
    variant = {}
    note = route
    if "continuation" in c.features:
        variant["split_at"] = max(1, len(c.spec_points) // 2)
        if "a4_continuation" in c.features:
            variant["cont_size"] = {A4: LETTER, LETTER: A4, A4_LANDSCAPE: LETTER_LANDSCAPE}[h["size"]]
    if "scramble" in c.features:
        variant["scramble"] = True
    if "watermark" in c.features:
        word = rnd.choice(["DRAFT", "COPY", "VENDOR COPY"])

        def pre(pen, word=word):
            pen.c.saveState()
            pen.c.setFillColorRGB(0.86, 0.86, 0.86)
            pen.c.setFont(h["font"] + "-Bold", 96 if len(word) < 6 else 60)
            pen.c.translate(pen.w / 2, pen.h / 2)
            pen.c.rotate(35)
            pen.c.drawCentredString(0, -30, word)
            pen.c.restoreState()
        variant["pre"] = pre
    if "white_decoy" in c.features:
        pg = Page(c)
        p = rnd.choice(c.spec_points)
        s = c.sizes_measured[0]
        decoy = pg.q(c.true[(p["code"], s, 1)] + 2 * p["tol_plus"])

        def post(pen, text=f"{p['code']} {pg.name(p)} {s}: {decoy}"):
            pen.text(54, text, 8.5, y=pen.h - 34, fill=(1, 1, 1))
        variant["post"] = post
        note += f" white decoy {p['code']} {decoy}"

    if route in FORM_ROUTES:
        build_form(c, path, mismatch=route == "form_mismatch")
        set_meta(path, h["meta"])
        shutil.rmtree(td)
        return note

    pg = Page(c)
    stamps = {k: correction_stamp(pg.q(v["right"]), rnd) for k, v in c.corrections.items() if v["kind"] == "stamp"}
    if stamps:
        variant["stamps"] = stamps
        note += f": stamped correction on {', '.join(map(str, stamps))}"
    pen = render(c, base, variant)

    def wrong_base():
        # the OCR layer is read from a report with altered measured values; the page images stay right
        wrong = copy.deepcopy(c)
        for key, val in wrong.printed.items():
            if val is not None and rnd.random() < 0.5:
                wrong.printed[key] = val + rnd.choice([-2, -1, 1, 2]) * F(1) + rnd.choice([F(0), wrong.printed_prec])
        wbase = os.path.join(td, "wrong.pdf")
        render(wrong, wbase, variant)
        return wbase

    finish(route, base, path, rnd, h["meta"], h["size"], wrong_base)
    if route == "scan_wrong_ocr":
        note += ": OCR layer read from altered values; the image is right"
    annots = [(k, v) for k, v in c.corrections.items() if v["kind"] == "annot"]
    for key, corr in annots:        # digital only: the output is the drawn page, so the cell boxes hold
        page_no, x0, top, x1, bottom = pen.cells[key]
        ph = pen.page_sizes[page_no][1]
        freetext_correction(path, page_no - 1, (x0 - 1, ph - bottom - 1, max(x1, x0 + 34) + 1, ph - top + 1), pg.q(corr["right"]))
        note += f": annotation corrects {key}"
    shutil.rmtree(td)
    return note


def render_item(item, path, rng):
    """Draw the item through its route. Returns the production note for the manifest."""
    return produce(item, path, rng)

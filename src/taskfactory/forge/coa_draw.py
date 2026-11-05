"""The certificate of analysis drawn and sent through its production route; lifted from the coa pack. Runs inside the coa generator
image (fonts, Ghostscript, Tesseract, OCRmyPDF). Ported from coa-intake's gen2.py; `render(item, path, rng)`
continues the item's own random stream, exactly as gen2 did after apply_features. The domain-free parts (the
pen, the routes, the overlays) live in taskfactory.forge.docforge."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile

import pikepdf

from taskfactory.forge.docforge import (Pen, find_word, finish, freetext_correction, page_count, set_meta,
                                        stamp_image, wrap)

from taskfactory.forge.coa_doc import *  # noqa: F403  the certificate model, catalogue and helpers

def draw_header(pen, c: Cert, continued=False, revision=None):
    h = c.house
    k = c.house_key
    title = "CERTIFICATE OF ANALYSIS"
    if revision:
        title += f", REVISION {revision}"
    elif continued:
        title += " (continued)"
    if k == "hengxin":
        pen.text(54, h["name"], 14, bold=True); pen.y += 13
        pen.text(54, h["address"], 8.5); pen.y += 24
        pen.text(pen.w / 2, title, 13, bold=True, align="center"); pen.y += 7
        pen.line(54, pen.w - 54, width=1.2); pen.y += 2.5; pen.line(54, pen.w - 54, width=0.4); pen.y += 20
    elif k == "nordvik":
        pen.text(54, h["name"], 16, bold=True); pen.y += 14
        pen.text(54, h["address"], 8.5); pen.y += 6
        pen.line(54, pen.w - 54, width=0.8); pen.y += 20
        pen.text(54, title.title().replace("Of", "of"), 12, bold=True); pen.y += 20
    elif k == "pradesh":
        pen.text(pen.w / 2, h["name"].upper(), 15, bold=True, align="center"); pen.y += 14
        pen.text(pen.w / 2, h["address"], 9, align="center"); pen.y += 24
        pen.text(pen.w / 2, title, 13, bold=True, align="center"); pen.y += 3
        tw = pen.width(title, 13, True)
        pen.line(pen.w / 2 - tw / 2, pen.w / 2 + tw / 2, width=0.8); pen.y += 22
    else:
        pen.text(54, h["name"], 13, bold=True); pen.y += 12
        pen.text(54, h["address"], 8.5); pen.y += 22
        pen.text(54, ("Certificate of Analysis / QC Release" if not (continued or revision) else title.title()),
                 12, bold=True); pen.y += 8
        pen.line(54, pen.w - 54, width=0.5); pen.y += 18


def label_value(pen, label, value, x=54, vx=None, size=10):
    vx = vx or x + 120
    pen.text(x, label + ":", size, bold=True)
    if value is not None:
        pen.text(vx, value, size)
    pen.y += 14


def lot_dates(c, lot, override=None):
    o = override or {}
    retest = o.get("retest", lot["retest"])
    ds = c.house["date_style"]
    if retest:
        return c.house["retest_label"], fmt_date(retest, ds) if isinstance(retest, dt.date) else retest
    return c.house["expiry_label"], fmt_date(lot["expiry"], ds)


def draw_identity_single(pen, c, lot, with_product=True, override=None):
    h = c.house
    ds = h["date_style"]
    if with_product:
        label_value(pen, h["product_label"], c.material[0])
    lv = (override or {}).get("lot_number", lot["lot_number"])
    label_value(pen, h["lot_label"], lv)
    label_value(pen, h["mfg_label"], (override or {}).get("mfg", fmt_date(lot["mfg"], ds)))
    lab, val = lot_dates(c, lot, override)
    label_value(pen, lab, val)


def draw_extras(pen, c):
    for label, kind in c.house["extras"]:
        v = {"issue": fmt_date(c.issue, c.house["date_style"]), "qty": f"{c.rnd.choice([25, 50, 200, 500])} kg",
             "storage": "Store below 25 °C in a dry place"}[kind]
        label_value(pen, label, v)


def cell_text(row, key, lot_rows=None):
    if key == "test":
        return row["test"], None
    if key == "spec":
        return row["spec_text"], None
    if key == "result":
        return (row["result"] or ""), row["marker"]
    if key == "unit":
        return (row["unit"] or ""), None
    if key == "result_unit":
        res = row["result"] or ""
        if row["marker"] and row["unit"]:
            return res, row["marker"] + "|" + row["unit"]
        return (res + (" " + row["unit"] if row["unit"] and res else "")), row["marker"]
    if key == "loq":
        return (f"{row['loq'][0]} {row['loq'][1]}" if row["loq"] else ""), None
    raise KeyError(key)


def draw_table(pen, c, cols, rows_of, n_rows, page_bottom, on_new_page, size=9.5, lh=12, order_reverse=False,
               break_at=None):
    """cols: [(header, width, getter(i) -> (text, marker))]. Breaks across pages at page_bottom."""
    x0 = 54
    total = sum(w for _, w, _ in cols)

    def header():
        x = x0
        for head, w, _ in cols:
            pen.text(x + 3, head, size, bold=True)
            x += w
        pen.y += 5
        pen.line(x0, x0 + total, width=0.8)
        pen.y += lh + 1

    header()
    for i in range(n_rows):
        cells = [g(i) for _, _, g in cols]
        depth = max(len(wrap(pen, t, w, size)) for (t, _), (_, w, _) in zip(cells, cols))
        if pen.y + depth * lh > page_bottom or (break_at and i == break_at):
            on_new_page()
            header()
        x = x0
        placements = []
        for (text, mark), (_, w, _) in zip(cells, cols):
            for k, piece in enumerate(wrap(pen, text, w, size)):
                placements.append((x + 3, pen.y + k * lh, piece, mark if k == 0 else None))
            x += w
        if order_reverse:
            placements = list(reversed(placements))
            for px, py, piece, mark in placements:     # each word emitted separately, last word first
                sup, tail = False, None
                if mark and "|" in mark:               # marker then unit, as in the plain branch below
                    m, tail = mark.split("|")
                    sup = m == "sup"
                    piece = piece if sup else piece + m
                elif mark == "sup":
                    sup = True
                elif mark:
                    piece += mark
                words, cx = piece.split(" "), px
                spots = []
                for k, wd in enumerate(words):
                    spots.append((cx, wd, sup and k == len(words) - 1))
                    cx += pen.width(wd + " ", size)
                if tail:
                    spots.append((px + pen.width(piece, size) + (8 if sup else pen.width(" ", size)), tail, False))
                for sx, wd, s_up in reversed(spots):
                    pen.text(sx, wd, size, y=py, sup="a" if s_up else None)
        else:
            for px, py, piece, mark in placements:
                if mark and "|" in mark:               # marker then unit, e.g. "0.42* mg/kg"
                    m, unit = mark.split("|")
                    if m == "sup":
                        pen.text(px, piece, size, y=py, sup="a")
                        pen.text(px + pen.width(piece, size) + 8, unit, size, y=py)
                    else:
                        pen.text(px, f"{piece}{m} {unit}", size, y=py)
                elif mark == "sup":
                    pen.text(px, piece, size, y=py, sup="a")
                elif mark:
                    pen.text(px, piece + mark, size, y=py)
                else:
                    pen.text(px, piece, size, y=py)
        pen.y += (depth - 1) * lh + 4
        pen.line(x0, x0 + total, width=0.3)
        pen.y += lh


def draw_notes(pen, c, lot_index=None):
    lines = [n for n in c.notes if n.get("lot") in (None, lot_index) or lot_index is None]
    if not lines:
        return
    pen.y += 4
    for n in lines:
        if n.get("sup"):
            pen.text(54, "a", 6.5, y=pen.y - 3)
            pen.text(59, n["text"][2:], 8.5)
        else:
            pen.text(54, ("Note: " if not n["text"].startswith("*") else "") + n["text"], 8.5)
        pen.y += 11


def amendment_block(pen, c):
    revs = sorted(c.revisions, key=lambda r: (r["rev"], r["lot"]))
    if not revs:
        return
    pen.y += 10
    pen.text(54, "Amendments", 10, bold=True); pen.y += 14
    for r in revs:
        lot = c.lots[r["lot"]]
        if r["kind"] == "result":
            row = lot["rows"][r["row"]]
            val = r["value"] + (f" {row['unit']}" if row["unit"] else "")
            what = f"{row['test']} result revised to {val}"
        else:
            what = f"{c.house['retest_label']} revised to {fmt_date(r['value'], c.house['date_style'])}"
        pen.text(54, f"Revision {r['rev']} ({fmt_date(c.issue + dt.timedelta(days=7 * r['rev']), c.house['date_style'])}),"
                     f" {c.house['lot_label']} {lot['lot_number']}: {what}.", 8.5)
        pen.y += 12


def draw_footer(pen, c):
    pen.y += 16
    signer = {"hengxin": "QA Manager: Li Wei", "nordvik": "Approved: Kari Solberg, Quality Assurance",
              "pradesh": "Checked by: QC Officer        Approved by: QA Head", "bluewater": "Released by: QC Release"}[c.house_key]
    pen.text(54, signer, 9); pen.y += 12
    pen.text(54, "This certificate was generated electronically and is valid without signature.", 7.5)


def result_cols(c, lot):
    cols = []
    for head, key, w in c.house["cols"]:
        if key == "loq" and not any(r["loq"] for r in lot["rows"]):
            continue
        cols.append((head, w, (lambda key: (lambda i: cell_text(lot["rows"][i], key)))(key)))
    return cols


def render(c: Cert, path, variant=None):
    """Draw the certificate with reportlab. variant: dict of drawing switches for routes."""
    v = variant or {}
    h = c.house
    pen = Pen(path, h, v.get("size"))
    bottom = v.get("page_bottom", pen.h - 70)
    ds = h["date_style"]

    state = {"lot": c.lots[0]}

    def new_page(rev=None, fresh=False):
        pen.new_page(v.get("cont_size"))
        if v.get("pre"):
            v["pre"](pen)
        draw_header(pen, c, continued=rev is None and not fresh, revision=rev)
        if rev is None and not fresh:
            lots = c.lots if h["multi"] == "columns" and len(c.lots) > 1 else [state["lot"]]
            pen.text(54, f"{h['lot_label']}: " + ", ".join(l["lot_number"] for l in lots), 9.5, bold=True)
            pen.y += 18

    if v.get("pre"):
        v["pre"](pen)
    draw_header(pen, c)
    stamp_ref = v.get("stamp_ref")             # ("lot"|"retest", stamp text)
    if h["multi"] == "columns" and len(c.lots) > 1:
        label_value(pen, h["product_label"], c.material[0])
        draw_extras(pen, c)
        pen.y += 4
        x = 54
        heads = [h["lot_label"], h["mfg_label"], "Re-test / Expiry"]
        for k, head in enumerate(heads):
            pen.text(x + [0, 110, 250][k], head, 9.5, bold=True)
        pen.y += 4; pen.line(54, 470, width=0.5); pen.y += 13
        for lot in c.lots:
            lab, val = lot_dates(c, lot)
            pen.text(54, lot["lot_number"], 9.5); pen.text(164, fmt_date(lot["mfg"], ds), 9.5)
            pen.text(304, f"{val} ({'re-test' if lot['retest'] else 'expiry'})", 9.5)
            pen.y += 13
        pen.y += 10
        rows0 = c.lots[0]["rows"]
        cols = [(h["cols"][0][0], 150, lambda i: (rows0[i]["test"], None)),
                (h["cols"][1][0], 110, lambda i: (rows0[i]["spec_text"], None))]
        for li, lot in enumerate(c.lots):
            cols.append((lot["lot_number"], 230 // len(c.lots) + 20,
                         (lambda lot: (lambda i: cell_text(lot["rows"][i], "result_unit")))(lot)))
        draw_table(pen, c, cols, None, len(rows0), bottom, new_page, order_reverse=v.get("scramble"),
                   break_at=len(rows0) // 2 + 1 if v.get("split") else None)
        draw_notes(pen, c)
    else:
        for li, lot in enumerate(c.lots):
            state["lot"] = lot
            if li > 0:
                if h["multi"] == "pages":
                    new_page(fresh=True)
                else:
                    pen.y += 16
                    if pen.y > bottom - 200:
                        new_page()
            if li == 0 or h["multi"] == "pages":
                label_value(pen, h["product_label"], c.material[0])
            if stamp_ref and li == 0:
                kind, _ = stamp_ref
                ov = {"lot_number": "see stamp"} if kind == "lot" else {"retest": "see stamp"}
                draw_identity_single(pen, c, lot, with_product=False, override=ov)
            else:
                draw_identity_single(pen, c, lot, with_product=False)
            if li == 0:
                draw_extras(pen, c)
            pen.y += 8
            draw_table(pen, c, result_cols(c, lot), None, len(lot["rows"]), bottom, new_page,
                       order_reverse=v.get("scramble"),
                       break_at=len(lot["rows"]) // 2 + 1 if v.get("split") and li == len(c.lots) - 1 else None)
            draw_notes(pen, c, li)
    if c.revisions and v.get("revisions") == "block":
        amendment_block(pen, c)
    draw_footer(pen, c)
    if c.revisions and v.get("revisions") == "page":
        by_lot = {}
        for r in sorted(c.revisions, key=lambda r: r["rev"]):
            by_lot.setdefault((r["lot"], r["rev"]), []).append(r)
        for (li, rev), rs in sorted(by_lot.items(), key=lambda kv: kv[0][1]):
            lot = copy.deepcopy(c.lots[li])
            ov = {}
            for r in rs:
                if r["kind"] == "result":
                    lot["rows"][r["row"]]["result"] = r["value"]
                else:
                    ov["retest"] = r["value"]
                    lot["retest"] = r["value"]
            new_page(rev=rev)
            pen.text(54, f"This revision replaces the values below for {h['lot_label']} {lot['lot_number']}.", 9)
            pen.y += 18
            label_value(pen, h["product_label"], c.material[0])
            draw_identity_single(pen, c, lot, with_product=False)
            pen.y += 8
            draw_table(pen, c, result_cols(c, lot), None, len(lot["rows"]), bottom, new_page)
            draw_footer(pen, c)
    if v.get("post"):
        v["post"](pen)
    pen.save()
    return pen


def build_form(c: Cert, path, mismatch):
    """A fillable form (reportlab AcroForm): identity and results are field values with appearances."""
    h = c.house
    pen = Pen(path, h)
    draw_header(pen, c)
    lot = c.lots[0]
    form = pen.c.acroForm
    ds = h["date_style"]

    def field(label, name, value, x=54, w=210):
        pen.text(x, label + ":", 10, bold=True)
        form.textfield(name=name, value=value, x=x + 120, y=pen.h - pen.y - 4, width=w, height=15,
                       fontName="Helvetica", fontSize=10, borderWidth=0.5, borderColor=None,
                       fillColor=None, textColor=None, forceBorder=False)
        pen.y += 19

    field(h["product_label"], "product", c.material[0], w=260)
    field(h["lot_label"], "lot", lot["lot_number"])
    field(h["mfg_label"], "mfg", fmt_date(lot["mfg"], ds))
    lab, val = lot_dates(c, lot)
    field(lab, "d2", val)
    draw_extras(pen, c)
    pen.y += 10
    x0 = 54
    heads = [("Analysis", 0), ("Limit", 175), ("Result", 300), ("Units", 400)]
    for head, dx in heads:
        pen.text(x0 + dx + 3, head, 9.5, bold=True)
    pen.y += 5; pen.line(x0, x0 + 470, width=0.8); pen.y += 14
    for i, r in enumerate(lot["rows"]):
        pen.text(x0 + 3, r["test"], 9.5)
        pen.text(x0 + 178, r["spec_text"], 9.5)
        wide = len(r["result"] or "") > 12
        form.textfield(name=f"result_{i}", value=(r["result"] or "") + ("*" if r["marker"] else ""), x=x0 + 300, y=pen.h - pen.y - 4,
                       width=170 if wide else 95, height=14, fontName="Helvetica", fontSize=9.5, borderWidth=0.4,
                       borderColor=None, fillColor=None, textColor=None, forceBorder=False)
        if not wide:
            pen.text(x0 + 403, r["unit"] or "", 9.5)
        pen.y += 18
    draw_notes(pen, c)
    draw_footer(pen, c)
    pen.save()
    if mismatch:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            for annot in pdf.pages[0].get("/Annots", []):
                name = str(annot.get("/T", ""))
                v = str(annot.get("/V", ""))
                if name.startswith("result_") and v.replace(".", "").isdigit():
                    annot.V = pikepdf.String(str(round_to(D(v) * 3 + 1, 2)))
                if name == "lot":
                    annot.V = pikepdf.String(lot["lot_number"][0] + "000000")
            if "/AcroForm" in pdf.Root:
                pdf.Root.AcroForm.NeedAppearances = False
            pdf.save(path)


def produce(c: Cert, path, rnd):
    """Render the certificate through its production route. Returns notes for the manifest."""
    route = c.route
    h = c.house
    td = tempfile.mkdtemp()
    base = os.path.join(td, "base.pdf")
    variant = {"revisions": c.revision_style} if c.revisions else {}
    note = route
    if "continuation" in c.features:
        variant["split"] = True
        if "a4_continuation" in c.features:
            variant["cont_size"] = LETTER if h["size"] == A4 else A4
    if "scramble" in c.features:
        variant["scramble"] = True
    if "watermark" in c.features:
        def pre(pen):
            pen.c.saveState()
            pen.c.setFillColorRGB(0.86, 0.86, 0.86)
            pen.c.setFont(h["font"] + "-Bold", 120)
            pen.c.translate(pen.w / 2, pen.h / 2)
            pen.c.rotate(35)
            pen.c.drawCentredString(0, -40, "COPY")
            pen.c.restoreState()
        variant["pre"] = pre
    stamp = None
    if "stamp_lot" in c.features or "stamp_retest" in c.features:
        lot = c.lots[0]
        if "stamp_lot" in c.features:
            stamp = ("lot", f"LOT {lot['lot_number']}")
        else:
            d = lot["retest"] or lot["expiry"]
            stamp = ("retest", f"RETEST {d.strftime('%d %b %Y').upper()}")
        variant["stamp_ref"] = stamp
        simg = stamp_image(stamp[1], rnd)
        sw, sh = simg.width * 0.36, simg.height * 0.36
        # the stamp goes on page 1 next to the identity block, never over a printed word: a dry draw of the page
        # without it gives the words' boxes, and the stamp takes the highest clear place at the right margin
        dry = render(c, os.path.join(td, "dry.pdf"), dict(variant))
        words = [b for b in dry.boxes if b[0] == 1]
        sx = dry.w - 54 - sw
        clear = lambda y: not any(b[1] < sx + sw + 4 and b[3] > sx - 4 and b[2] < y + sh + 4 and b[4] > y - 4
                                  for b in words)
        sy = next((y for y in range(112, int(dry.h / 2)) if clear(y)), 112)
        prev = variant.get("pre")

        def pre_stamp(pen, simg=simg, prev=prev, sx=sx, sy=sy):
            if prev:
                prev(pen)
            # by page number, not a one-shot flag: the correction redraws the certificate with this variant
            if pen.page_no == 1:
                pen.image(simg, sx, sy, sw, sh)
        variant["pre"] = pre_stamp
    if "white_decoy" in c.features:
        decoy = f"{c.lots[0]['lot_number'][0]}{rnd.randint(100000, 999999)}"

        def post(pen, decoy=decoy):
            pen.text(54, f"{h['lot_label']}: {decoy}", 9, y=pen.h - 40, fill=(1, 1, 1))
        variant["post"] = post
        note += f" white decoy lot {decoy}"

    if route == "form" or route == "form_mismatch":
        build_form(c, path, mismatch=route == "form_mismatch")
        set_meta(path, h["meta"])
        shutil.rmtree(td)
        return note
    render(c, base, variant)

    def wrong_base():
        # the OCR layer is read from a certificate with altered results; the page images stay right
        wrong = copy.deepcopy(c)
        for lot in wrong.lots:
            for r in lot["rows"]:
                if r["result"] and any(ch.isdigit() for ch in r["result"]) and rnd.random() < 0.6:
                    r["result"] = r["result"].translate(str.maketrans("0123456789", "8765432109"))
        wbase = os.path.join(td, "wrong.pdf")
        render(wrong, wbase, variant)
        return wbase

    finish(route, base, path, rnd, h["meta"], c.house["size"], wrong_base)
    if route == "scan_wrong_ocr":
        note += ": OCR layer read from altered values; the image is right"
    if "annot_correction" in c.features:
        lot = c.lots[0]
        cand = [r for r in lot["rows"] if r["result"] and r["result"].replace(".", "").isdigit() and not r["marker"]]
        r = rnd.choice(cand)
        true = r["result"]
        # the printed value is wrong; draw the certificate again with it, then correct it with the annotation
        wrong = str(round_to(D(true) * 10 + 1, max(decimals(true), 1)))
        r["result"] = wrong
        render(c, base, variant)
        shutil.copy(base, path)
        set_meta(path, h["meta"])
        # the row can sit on a continuation page
        pi = next(i for i in range(page_count(path)) if find_word(path, wrong, i, missing_ok=True))
        x0, y0, x1, y1 = find_word(path, wrong, pi)
        r["result"] = true
        # cover the printed number only: a unit printed in the same cell stays visible
        freetext_correction(path, pi, (x0 - 2, y0 - 2.5, max(x1, x0 + 5.5 * len(true)) + 2, y1 + 2), true)
        note += f": printed {wrong} corrected by annotation to {true} for {r['test']}"
    shutil.rmtree(td)
    return note


def render_item(item, path, rng):
    """Draw the item through its route. Returns the production note for the manifest."""
    return produce(item, path, rng)

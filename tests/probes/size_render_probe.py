"""Runs inside the size-set gen image: draws reports and prints what each page shows, as JSON."""
import json
import random
import sys

sys.path.insert(0, "/tf/src")
sys.path.insert(0, "/pack")
import fitz  # noqa: E402
import pikepdf  # noqa: E402
import pack  # noqa: E402

out = {}
for cid, house, route, sizes, feats, key in json.loads(sys.argv[1]):
    rng = random.Random(key)  # the builder's key is "<seed>-<item id>"
    path = f"/tmp/{cid}.pdf"
    it = pack.build(cid, house, route, sizes, frozenset(feats), rng)
    before = json.dumps(pack.truth(it), sort_keys=True)
    try:
        note = pack.render(it, path, rng)
    except Exception as e:  # reported per item, so one failure does not hide the others
        import traceback
        out[cid] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
        continue
    doc = fitz.open(path)
    # words a correction annotation covers by more than half
    covered = []
    for page in doc:
        for a in page.annots():
            for w in page.get_text("words"):
                box = fitz.Rect(w[:4])
                if (box & a.rect).get_area() > box.get_area() / 2 and w[4] != a.info["content"]:
                    covered.append(w[4])
    # words any image (a stamp) overlaps, per page, and the number of images
    under, images = [], 0
    for page in doc:
        for img in page.get_images():
            images += 1
            for r in page.get_image_rects(img[0]):
                under += [w[4] for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(r)]
    fields = []
    with pikepdf.open(path) as pdf:
        for annot in pdf.pages[0].get("/Annots", []):
            if str(annot.get("/T", "")).startswith("m_"):
                fields.append((str(annot.get("/T")), str(annot.get("/V", ""))))
    sizes_pt = [(round(p.rect.width), round(p.rect.height), p.rotation) for p in doc]
    text = " ".join(p.get_text() for p in doc)
    truth = pack.truth(it)
    out[cid] = {"note": note, "pages": sizes_pt, "images": images, "covered": covered, "under_stamp": under,
                "fields": fields, "text_len": len(text), "text_head": text[:300], "text": text,
                "glyphs": sum(text.count(g) for g in "¼½¾⅛⅜⅝⅞"),
                "truth_same": before == json.dumps(truth, sort_keys=True),
                "measured": {f"{r['code']}|{r['size']}|{r['piece']}": r["measured"] for r in truth["measurements"]},
                "measured_on": truth["measured_on"], "decision": truth["decision"], "n_rows": len(truth["measurements"]),
                "printed_unit": it.printed_unit, "style": it.style, "has_style": it.style in text}
print(json.dumps(out))

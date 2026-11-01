"""Runs inside the coa gen image: draws certificates and prints what each page shows, as JSON."""
import json
import random
import sys

sys.path.insert(0, "/pack")
import fitz  # noqa: E402
import pack  # noqa: E402

out = {}
for cid, house, route, lots, feats, key in json.loads(sys.argv[1]):
    rng = random.Random(key)  # the builder's key is "<seed>-<item id>"
    path = f"/tmp/{cid}.pdf"
    it = pack.build(cid, house, route, lots, frozenset(feats), rng)
    pack.render(it, path, rng)
    doc = fitz.open(path)
    covered = []
    for page in doc:
        for a in page.annots():
            for w in page.get_text("words"):
                box = fitz.Rect(w[:4])
                if (box & a.rect).get_area() > box.get_area() / 2 and w[4] != a.info["content"]:
                    covered.append(w[4])
    # the words on the first lot's marked row, left to right (the superscript mark is a word of its own)
    marked_line = []
    for page in doc[:1]:
        ws = page.get_text("words")
        hits = [w for w in ws if w[4] == "drying"]
        if hits:
            y = hits[0][3]
            marked_line = [w[4] for w in sorted(ws, key=lambda w: w[0]) if abs(w[3] - y) < 4 and w[0] > hits[0][0]
                           and w[0] < page.rect.width * 0.55]
    # words of the first page that the stamp image overlaps at all
    under_stamp = []
    for img in doc[0].get_images():
        for r in doc[0].get_image_rects(img[0]):
            under_stamp += [w[4] for w in doc[0].get_text("words") if fitz.Rect(w[:4]).intersects(r)]
    out[cid] = {"images": len(doc[0].get_images()), "covered": covered, "marked_line": marked_line,
                "under_stamp": under_stamp}
print(json.dumps(out))

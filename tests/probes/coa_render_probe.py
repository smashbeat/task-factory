"""Runs inside the coa gen image: draws certificates and prints what each page shows, as JSON."""
import json
import random
import sys

sys.path.insert(0, "/pack")
import fitz  # noqa: E402
import model  # noqa: E402
import render  # noqa: E402

out = {}
for cid, house, route, lots, feats in json.loads(sys.argv[1]):
    c = model.Cert(cid, house, random.Random(f"probe-{cid}"), lots, set(feats), route)
    model.apply_features(c)
    path = f"/tmp/{cid}.pdf"
    render.produce(c, path, random.Random(f"probe-{cid}"))
    page = fitz.open(path)[0]
    covered = []
    for a in page.annots():
        for w in page.get_text("words"):
            box = fitz.Rect(w[:4])
            if (box & a.rect).get_area() > box.get_area() / 2 and w[4] != a.info["content"]:
                covered.append(w[4])
    out[cid] = {"images": len(page.get_images()), "covered": covered}
print(json.dumps(out))

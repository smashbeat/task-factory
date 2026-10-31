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
    pack.render(pack.build(cid, house, route, lots, frozenset(feats), rng), path, rng)
    doc = fitz.open(path)
    covered = []
    for page in doc:
        for a in page.annots():
            for w in page.get_text("words"):
                box = fitz.Rect(w[:4])
                if (box & a.rect).get_area() > box.get_area() / 2 and w[4] != a.info["content"]:
                    covered.append(w[4])
    out[cid] = {"images": len(doc[0].get_images()), "covered": covered}
print(json.dumps(out))

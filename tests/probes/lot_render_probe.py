"""Runs inside the lot-release gen image: draws packages and prints what their files hold, as JSON."""
import csv
import email
import email.policy
import email.utils
import io
import json
import os
import random
import sys

sys.path.insert(0, "/tf/src")
sys.path.insert(0, "/pack")
import fitz  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

import pack  # noqa: E402

out = {}
for cid, style, route, units, feats, key in json.loads(sys.argv[1]):
    rng = random.Random(key)
    path = f"/tmp/{cid}.pkg"
    it = pack.build(cid, style, route, units, frozenset(feats), rng)
    before = json.loads(json.dumps(pack.truth(it)))
    note = pack.render(it, path, rng)
    after = json.loads(json.dumps(pack.truth(it)))
    files = sorted(os.listdir(path))
    info = {"files": files, "planned": sorted(f["name"] for f in it.files), "truth_unchanged": before == after,
            "note": note, "pdf_pages": 0, "pdfs": {}, "emails": {}, "xlsx": {}, "csv": {}, "label": {}}
    for name in files:
        full = os.path.join(path, name)
        if name.endswith(".xlsx"):
            wb = load_workbook(full, data_only=True)
            sheets = []
            for ws in wb.worksheets:
                cells = []
                for row in ws.iter_rows():
                    for c in row:
                        if c.value is not None:
                            cells.append({"ref": c.coordinate, "value": c.value if not hasattr(c.value, "isoformat") else c.value.isoformat(),
                                          "type": c.data_type, "format": c.number_format})
                hidden_rows = [r for r, d in ws.row_dimensions.items() if d.hidden]
                sheets.append({"title": ws.title, "state": ws.sheet_state, "hidden_rows": hidden_rows, "cells": cells,
                               "formulas": sum(1 for c in cells if c["type"] == "f")})
            info["xlsx"] = {"creator": wb.properties.creator, "sheets": sheets}
        elif name.endswith(".csv"):
            raw = open(full, "rb").read()
            text = raw.decode("utf-8-sig")
            delim = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
            rows = list(csv.reader(io.StringIO(text), delimiter=delim))
            info["csv"] = {"bom": raw.startswith(b"\xef\xbb\xbf"), "delimiter": delim, "rows": rows, "crlf": b"\r\n" in raw}
        elif name.endswith(".eml"):
            msg = email.message_from_bytes(open(full, "rb").read(), policy=email.policy.default)
            atts = [(a.get_filename(), a.get_content_type(), len(a.get_content()) if a.get_content_type() == "application/pdf" else 0)
                    for a in msg.iter_attachments()]
            inner = [p for p in msg.walk() if p.get_content_type() == "message/rfc822"]
            inner_atts = []
            for part in inner:
                m2 = part.get_content()
                inner_atts += [(a.get_filename(), a.get_content_type()) for a in m2.iter_attachments()]
            body = msg.get_body(("plain",))
            info["emails"][name] = {"date": msg["Date"], "ts": email.utils.parsedate_to_datetime(msg["Date"]).timestamp(),
                                    "in_reply_to": msg["In-Reply-To"], "subject": msg["Subject"], "attachments": atts,
                                    "forwarded": len(inner), "inner_attachments": inner_atts,
                                    "body": body.get_content() if body else ""}
            for a in msg.iter_attachments():
                if a.get_content_type() == "application/pdf":
                    doc = fitz.open(stream=a.get_content(), filetype="pdf")
                    info["pdf_pages"] += len(doc)
                    info["pdfs"][f"{name}:{a.get_filename()}"] = {"pages": len(doc), "text": len(doc[0].get_text().strip()),
                                                                  "images": len(doc[0].get_images()), "widgets": len(list(doc[0].widgets()))}
            for part in inner:
                for a in part.get_content().iter_attachments():
                    if a.get_content_type() == "application/pdf":
                        doc = fitz.open(stream=a.get_content(), filetype="pdf")
                        info["pdf_pages"] += len(doc)
                        info["pdfs"][f"{name}:fwd:{a.get_filename()}"] = {"pages": len(doc), "text": len(doc[0].get_text().strip()),
                                                                          "images": len(doc[0].get_images()), "widgets": len(list(doc[0].widgets()))}
        elif name.endswith(".pdf"):
            doc = fitz.open(full)
            info["pdf_pages"] += len(doc)
            info["pdfs"][name] = {"pages": len(doc), "text": len(doc[0].get_text().strip()), "images": len(doc[0].get_images()),
                                  "widgets": len(list(doc[0].widgets())), "words": doc[0].get_text().split()[:400]}
            if name == it.label["name"]:
                info["label"] = {"text": doc[0].get_text(), "pages": len(doc)}
    out[cid] = info
print(json.dumps(out, default=str))

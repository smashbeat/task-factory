"""The certificate of analysis as a document: the model, the catalogue, the supplier houses and the coa policy's
truth, with a switch per rule. Lifted from the coa pack so other packs can carry certificates inside their items.

Ported from coa-intake's gen2.py. `truth(off=...)` answers as an agent would if it ignored the rules in `off`;
those answers are the mutants the builder uses to prove each rule is tested and to attribute failures.
"""
from __future__ import annotations

import copy
import datetime as dt
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

SCAN_ROUTES = {"scan_ocr", "scan_wrong_ocr", "scan_no_ocr", "scan_rotated"}
LETTER = (612.0, 792.0)
A4 = (595.0, 842.0)

def norm(s):
    return "".join(unicodedata.normalize("NFKC", s).casefold().split())


UNIT_FACTOR = {norm(u): Decimal(f) for u, f in
               (("ppm", "1"), ("mg/kg", "1"), ("µg/g", "1"), ("ppb", "0.001"), ("µg/kg", "0.001"), ("%", "10000"))}


def convert(value: Decimal, unit, house_unit):
    """Value in the house unit, or None when the table cannot convert (policy 6)."""
    u = norm(unit) if unit else None
    h = norm(house_unit) if house_unit else None
    if u is None or u == h:
        return value
    if u in UNIT_FACTOR and h in UNIT_FACTOR:
        return value * UNIT_FACTOR[u] / UNIT_FACTOR[h]
    return None


def decimals(limit_text: str) -> int:
    return len(limit_text.split(".")[1]) if "." in limit_text else 0


def round_to(v: Decimal, places: int) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


ND_WORDS = ("nd", "notdetected", "<loq", "blq")


def evaluate(result, unit, test, loq, off=frozenset()):
    """True/False = meets/does not meet; None = no result (policy 6 and 7)."""
    lim = test["limit"]
    t = lim["type"]
    r = result.strip()
    low = r.lower()
    if t == "report":
        return True
    if t == "conforms":
        return low.startswith("conform") or low.startswith("compl") or low in ("pass", "passes")
    if t == "absent":
        return any(low.startswith(p) for p in ("absent", "not detected", "nd", "negative"))
    if norm(r) in ND_WORDS:
        if 7 in off:
            return True
        if loq is None:
            return None
        r, unit = "<" + loq[0], loq[1]
    lt = r.startswith("<")
    try:
        v = Decimal(r.lstrip("<").strip())
    except Exception:
        return False
    if 6 in off:
        places = lambda _: 12
    else:
        v = convert(v, unit, test["unit"])
        places = decimals
    if v is None:
        return None
    if t == "max":
        return round_to(v, places(lim["max"])) <= Decimal(lim["max"])
    if lt:
        return False
    if t == "min":
        return round_to(v, places(lim["min"])) >= Decimal(lim["min"])
    lo, hi = Decimal(lim["min"]), Decimal(lim["max"])
    return lo <= round_to(v, places(lim["min"])) and round_to(v, places(lim["max"])) <= hi


def disposition(spec, lot, off=frozenset()):
    """lot: truth lot plus '_loq' {row index: (value, unit)}."""
    received = dt.date.fromisoformat(spec["received"])
    d = lot["retest_date"] or lot["expiry_date"]
    if d and 8 not in off and dt.date.fromisoformat(d) <= received:
        return "reject"
    failing = missing = False
    for test in spec["tests"]:
        names = {norm(n) for n in test["names"]}
        idx = next((i for i, row in enumerate(lot["results"]) if norm(row["test"]) in names), None)
        if idx is None:
            missing = True
            continue
        row = lot["results"][idx]
        if row["result"] is None:
            missing = True
            continue
        ok = evaluate(row["result"], row["unit"], test, lot["_loq"].get(idx), off)
        if ok is None:
            missing = True
        elif not ok:
            failing = True
    return "reject" if failing else "incomplete" if missing else "accept"


# ------------------------------------------------------------------ catalogue

MATERIALS = [
    ("Ascorbic Acid USP", "Fine powder"),
    ("Zinc Citrate Trihydrate", "Granular"),
    ("Magnesium Bisglycinate", "Powder"),
    ("Cholecalciferol 100,000 IU/g", "Powder"),
    ("Ferrous Bisglycinate Chelate", "Powder"),
    ("Pyridoxine Hydrochloride USP", "Crystalline powder"),
    ("Calcium Carbonate (Precipitated)", "Powder"),
]

D = Decimal


def num(lo, hi, places):
    def f(rnd):
        return str(round_to(D(str(rnd.uniform(lo, hi))), places))
    return f


def choice(*xs):
    return lambda rnd: rnd.choice(xs)


# name, aliases, limit type, limit params (strings), house unit, passing result generator (house unit), kind
TESTS = [
    ("Appearance", ["Description"], "report", {}, None,
     choice("White to off-white powder", "Off-white powder", "White crystalline powder", "Fine white powder"), "text"),
    ("Identification (IR)", ["Identity (FTIR)", "Identification"], "conforms", {}, None,
     choice("Conforms", "Complies", "Conforms to reference"), "text"),
    ("Assay (on dried basis)", ["Assay", "Assay (HPLC)"], "range", {"min": "98.0", "max": "101.5"}, "%",
     num(98.4, 101.1, 1), "num"),
    ("Loss on drying", ["LOD"], "max", {"max": "0.5"}, "%", num(0.05, 0.42, 2), "num"),
    ("Residue on ignition", ["Sulfated ash"], "max", {"max": "0.10"}, "%", num(0.01, 0.08, 2), "num"),
    ("Lead (Pb)", ["Lead", "Pb"], "max", {"max": "1.0"}, "ppm", num(0.05, 0.6, 2), "metal"),
    ("Arsenic (As)", ["Arsenic", "As"], "max", {"max": "1.0"}, "ppm", num(0.05, 0.6, 2), "metal"),
    ("Cadmium (Cd)", ["Cadmium", "Cd"], "max", {"max": "0.5"}, "ppm", num(0.01, 0.3, 2), "metal"),
    ("Mercury (Hg)", ["Mercury", "Hg"], "max", {"max": "0.1"}, "ppm", num(0.005, 0.06, 3), "metal"),
    ("Total aerobic microbial count", ["TAMC", "Total plate count"], "max", {"max": "1000"}, "cfu/g",
     choice("<10", "<100", "40", "120", "230"), "micro"),
    ("Total yeast and mold", ["TYMC", "Yeasts and moulds"], "max", {"max": "100"}, "cfu/g",
     choice("<10", "20", "35"), "micro"),
    ("Escherichia coli (10 g)", ["E. coli (10 g)"], "absent", {}, None, choice("Absent", "Negative"), "text"),
    ("Salmonella spp. (25 g)", ["Salmonella (25 g)"], "absent", {}, None, choice("Absent", "Not detected"), "text"),
    ("Particle size (through 80 mesh)", ["Mesh (80)"], "min", {"min": "95.0"}, "%", num(96.0, 99.8, 1), "num"),
    ("Bulk density", ["Bulk density (untapped)"], "range", {"min": "0.45", "max": "0.75"}, "g/mL",
     num(0.5, 0.7, 2), "num"),
    ("pH (1% solution)", ["pH"], "range", {"min": "5.5", "max": "7.5"}, None, num(5.8, 7.2, 1), "num"),
]
TEST_BY_NAME = {t[0]: t for t in TESTS}
METALS = [t[0] for t in TESTS if t[6] == "metal"]

HOUSES = {
    "hengxin": dict(
        name="Hengxin Nutrition Co., Ltd.", address="No. 88 Keyuan Road, Suzhou, Jiangsu 215000, China",
        font="Liberation", size=LETTER, date_style="iso", multi="columns",
        lot_label="Batch No.", mfg_label="Date of Manufacture", retest_label="Re-test Date", expiry_label="Expiry Date",
        product_label="Product Name", cols=[("Test Item", "test", 165), ("Standard", "spec", 120),
                                            ("Result", "result", 95), ("Unit", "unit", 55)],
        spec_style="sym", extras=[("Date of Issue", "issue"), ("Quantity", "qty")],
        meta={"Producer": "ReportLab PDF Library - www.reportlab.com", "Creator": "Hengxin LIMS QC-Report 5.1"}),
    "nordvik": dict(
        name="Nordvik Ingredients AS", address="Industriveien 12, 1385 Asker, Norway",
        font="DejaVuSerif", size=A4, date_style="dmy", multi="sections",
        lot_label="Lot No.", mfg_label="Manufacture Date", retest_label="Retest Date", expiry_label="Expiry Date",
        product_label="Product", cols=[("Parameter", "test", 175), ("Result", "result_unit", 120),
                                       ("Specification", "spec", 140)],
        spec_style="maxmin", extras=[("Issued", "issue"), ("Storage", "storage")],
        meta={"Creator": "PScript5.dll Version 5.2.2", "Title": "Microsoft Word - CoA"}),
    "pradesh": dict(
        name="Pradesh Phytochem Pvt. Ltd.", address="Plot 14, MIDC Bhosari, Pune 411026, India",
        font="Carlito", size=LETTER, date_style="mdy", multi="pages",
        lot_label="Lot Number", mfg_label="Mfg. Date", retest_label="Retest Date", expiry_label="Exp. Date",
        product_label="Name of Product", cols=[("Test", "test", 150), ("Specification", "spec", 120),
                                                ("Result", "result", 80), ("Unit", "unit", 50), ("LOQ", "loq", 60)],
        spec_style="nmt", extras=[("Analysis Date", "issue"), ("Pack Size", "qty")],
        meta={"Creator": "Canon iR-ADV C5535", "Producer": "Adobe PSL 1.3e for Canon"}),
    "bluewater": dict(
        name="Bluewater Biochem Inc.", address="4120 Commerce Dr, Reno, NV 89502, USA",
        font="Roboto", size=LETTER, date_style="mdy", multi="sections",
        lot_label="Lot #", mfg_label="Manufactured", retest_label="Retest By", expiry_label="Expires",
        product_label="Material", cols=[("Analysis", "test", 170), ("Limit", "spec", 120), ("Result", "result", 95),
                                        ("Units", "unit", 55)],
        spec_style="nmt", extras=[("Release Date", "issue")],
        meta={"Producer": "ReportLab PDF Library - www.reportlab.com", "Creator": "QCForms 3.2"}),
}


def fmt_date(d: dt.date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "dmy":
        return d.strftime("%d-%b-%Y")
    return d.strftime("%B %d, %Y")


def supplier_spec(test, unit_shown, style):
    """The supplier's own specification text, in the unit the certificate prints."""
    name, _, t, p, hu, _, _ = test
    def conv(x):
        if unit_shown and hu and norm(unit_shown) != norm(hu) and norm(unit_shown) in UNIT_FACTOR:
            v = D(x) * UNIT_FACTOR[norm(hu)] / UNIT_FACTOR[norm(unit_shown)]
            return format(v.normalize(), "f")
        return x
    u = f" {unit_shown}" if unit_shown else ""
    if t == "max":
        return {"sym": f"≤ {conv(p['max'])}{u}", "maxmin": f"max. {conv(p['max'])}{u}"}.get(style, f"NMT {conv(p['max'])}{u}")
    if t == "min":
        return {"sym": f"≥ {conv(p['min'])}{u}", "maxmin": f"min. {conv(p['min'])}{u}"}.get(style, f"NLT {conv(p['min'])}{u}")
    if t == "range":
        sep = {"sym": " ~ ", "maxmin": " - "}.get(style, " to ")
        return f"{p['min']}{sep}{p['max']}{u}"
    if t == "absent":
        return {"sym": "Negative/10 g" if "10 g" in name else "Negative/25 g"}.get(style, "Absent")
    if t == "conforms":
        return "Conforms to standard" if style == "sym" else "Conforms"
    return "Report" if style != "sym" else "/"


# ------------------------------------------------------------------ certificate model

class Cert:
    """Everything that is printed, and the truth derived from it."""

    def __init__(self, cid, house, rnd, n_lots, features, route, *, houses=None, catalogue=None,
                 material=None, lot_numbers=None, received=None):
        """`house` is a key into `houses` (the coa houses by default) or a house dict of its own; `catalogue` is
        the test list (the raw-material one by default). `material`, `lot_numbers` and `received` override the
        random draws, which still happen in the same order, so a default call draws as it always did."""
        houses = HOUSES if houses is None else houses
        catalogue = TESTS if catalogue is None else catalogue
        by_name = {t[0]: t for t in catalogue}
        metals = [t[0] for t in catalogue if t[6] == "metal"]
        self.house = houses[house] if isinstance(house, str) else house
        self.house_key = house if isinstance(house, str) else house.get("key", "custom")
        self.id, self.rnd, self.features, self.route = cid, rnd, set(features), route
        self.material = rnd.choice(MATERIALS)
        if material is not None:
            self.material = material
        self.received = dt.date(2026, 10, rnd.randint(6, 20))
        if received is not None:
            self.received = received
        names = [t[0] for t in catalogue]
        must = []
        if self.features & {"units", "units_bad", "nd_loq_col", "nd_loq_note", "nd_no_loq", "nd_loq_high",
                            "round_metal"}:
            must += rnd.sample(metals, 2)
        if "round_min" in self.features and "Particle size (through 80 mesh)" in by_name:
            must.append("Particle size (through 80 mesh)")
        if "round_range" in self.features and "pH (1% solution)" in by_name:
            must.append("pH (1% solution)")
        if "wrap" in self.features and "Appearance" in by_name:
            must.append("Appearance")
        rest = [n for n in names if n not in must]
        chosen = set(must + rnd.sample(rest, min(len(rest), max(0, rnd.randint(7, 10) - len(must)))))
        self.tests = [by_name[n] for n in names if n in chosen]
        self.spec = {"material": self.material[0], "received": self.received.isoformat(),
                     "tests": [{"names": [t[0]] + t[1], "limit": {"type": t[2], **t[3]}, "unit": t[4]}
                               for t in self.tests]}
        self.notes = []          # printed note lines under the table
        self.revisions = []      # {"rev": n, "lot": i, "kind": "result"|"date", "row": j, "value": str, ...}
        self.loq_col = "loq" in [c[1] for c in self.house["cols"]]
        self.lots = [self._make_lot(k) for k in range(n_lots)]
        if lot_numbers:
            for lot, number in zip(self.lots, lot_numbers):
                lot["lot_number"] = number
        self.issue = self.received - dt.timedelta(days=rnd.randint(20, 60))

    def _make_lot(self, k):
        rnd = self.rnd
        mfg = dt.date(2026, rnd.randint(2, 8), rnd.randint(1, 28)) + dt.timedelta(days=7 * k)
        retest = rnd.random() < 0.65
        d2 = mfg + dt.timedelta(days=rnd.choice([365, 540, 730]))
        rows = []
        for t in self.tests:
            res = t[5](rnd)
            rows.append({"t": t, "test": t[0], "result": res, "unit": t[4], "spec_unit": t[4],
                         "marker": None, "loq": None})
        return {"lot_number": f"{rnd.choice('LBP')}{rnd.randint(100000, 999999)}", "mfg": mfg,
                "retest": d2 if retest else None, "expiry": None if retest else d2, "rows": rows}

    # truth -------------------------------------------------------
    def truth(self, off=frozenset()):
        out = {"lots": []}
        for li, lot in enumerate(self.lots):
            lot = copy.deepcopy(lot)
            if 3 in off and li == 0 and "stamp_retest" in self.features:
                lot["retest"] = None    # the date printed only in the stamp is missed
            if 4 in off:
                for row in lot["rows"]:
                    if row["marker"] and row["result"]:
                        row["result"] = row["result"] + "*"
            revs = [] if 5 in off else sorted((r for r in self.revisions if r["lot"] == li), key=lambda r: r["rev"])
            for r in revs:          # ascending, so the highest revision is applied last and wins
                if r["kind"] == "result":
                    lot["rows"][r["row"]]["result"] = r["value"]
                elif r["kind"] == "retest":
                    lot["retest"] = r["value"]
            rows, loq = [], {}
            shared = self.house["multi"] == "columns" and len(self.lots) > 1
            for j, row in enumerate(lot["rows"]):
                spec_text = self.lots[0]["rows"][j]["spec_text"] if shared else row["spec_text"]
                rows.append({"test": row["test"], "result": row["result"], "unit": row["unit"],
                             "specification": spec_text})
                if row["loq"]:
                    loq[j] = row["loq"]
            for note in self.notes:
                if note.get("loq_for") is not None and note["lot"] in (None, li):
                    loq[note["loq_for"]] = note["loq"]
            entry = {"material": self.material[0], "supplier": self.house["name"],
                     "lot_number": lot["lot_number"], "manufacture_date": lot["mfg"].isoformat(),
                     "retest_date": lot["retest"].isoformat() if lot["retest"] else None,
                     "expiry_date": lot["expiry"].isoformat() if lot["expiry"] else None,
                     "results": rows, "_loq": loq}
            entry["disposition"] = disposition(self.spec, entry, off)
            del entry["_loq"]
            out["lots"].append(entry)
        return out


# ------------------------------------------------------------------ features (rules A to F, plus v1 routes)

def apply_features(c: Cert):
    rnd, f = c.rnd, c.features
    lot0 = c.lots[0]
    metal_rows = lambda lot: [j for j, r in enumerate(lot["rows"]) if r["t"][6] == "metal"]
    if "alias" in f:                                     # rule 6 names
        for lot in c.lots:
            for j, r in enumerate(lot["rows"]):
                if r["t"][1] and (j % 2 == 0):
                    r["test"] = r["t"][1][0]
        # all lots of one certificate print the same names
        for lot in c.lots[1:]:
            for j, r in enumerate(lot["rows"]):
                r["test"] = lot0["rows"][j]["test"]
    if "units" in f or "round_metal" in f:               # rule 6 units and rounding on a metal
        j = metal_rows(lot0)[0]
        # µ only where the file keeps it as text: scans, outlines and redistilled files lose or blur it
        unit = rnd.choice(["mg/kg", "ppb", "µg/kg"]) if c.route in ("digital", "form", "form_mismatch") \
            else rnd.choice(["mg/kg", "ppb"])
        if "units" not in f:
            unit = "ppm"
        for lot in c.lots:
            r = lot["rows"][j]
            lim = D(r["t"][3]["max"])
            if "round_metal" in f and lot is lot0:
                v = lim + (D("0.05") if "round_fail" in f else D("0.04"))
            else:
                v = D(r["result"])
            shown = v * UNIT_FACTOR[norm("ppm")] / UNIT_FACTOR[norm(unit)]
            r["result"] = format(shown.normalize(), "f") if unit in ("ppb", "µg/kg") else str(v)
            r["unit"] = unit
            r["spec_unit"] = unit
    if "units_bad" in f:                                 # unconvertible unit: no result
        j = metal_rows(lot0)[-1]
        lots = c.lots if c.house["multi"] == "columns" else [lot0]
        for lot in lots:
            lot["rows"][j]["unit"] = "mg/L"
            lot["rows"][j]["spec_unit"] = "mg/L"
    if "round_min" in f:
        j = next(j for j, r in enumerate(lot0["rows"]) if r["test"].startswith("Particle") or r["t"][0].startswith("Particle"))
        lot0["rows"][j]["result"] = "94.96" if "round_fail" not in f else "94.94"
    if "round_range" in f:
        j = next(j for j, r in enumerate(lot0["rows"]) if r["t"][0].startswith("pH"))
        lot0["rows"][j]["result"] = "7.54" if "round_fail" not in f else "7.55"
    if f & {"nd_loq_col", "nd_loq_note", "nd_no_loq", "nd_loq_high"}:   # rule 7 detection limits
        js = metal_rows(lot0)
        for lot in c.lots:
            for j in js:
                lot["rows"][j]["result"] = rnd.choice(["ND", "Not detected", "<LOQ", "BLQ"]) if j == js[0] else lot["rows"][j]["result"]
        j = js[0]
        unit = lot0["rows"][j]["unit"] or "ppm"
        if "result_unit" in [k for _, k, _ in c.house["cols"]] or c.house["multi"] == "columns":
            for lot in c.lots:
                lot["rows"][j]["unit"] = None
        lim = D(lot0["rows"][j]["t"][3]["max"])
        hi = lim * 2 * UNIT_FACTOR[norm("ppm")] / UNIT_FACTOR[norm(unit)] if norm(unit) in UNIT_FACTOR else lim * 2
        lo = D("0.05") * UNIT_FACTOR[norm("ppm")] / UNIT_FACTOR[norm(unit)] if norm(unit) in UNIT_FACTOR else D("0.05")
        loq_val = format((hi if "nd_loq_high" in f else lo).normalize(), "f")
        if "nd_loq_col" in f and c.loq_col:
            for lot in c.lots:
                lot["rows"][j]["loq"] = (loq_val, unit)
        elif "nd_loq_note" in f or "nd_loq_high" in f or ("nd_loq_col" in f and not c.loq_col):
            name = lot0["rows"][j]["test"]
            c.notes.append({"text": f"LOQ for {name}: {loq_val} {unit}", "loq_for": j, "loq": (loq_val, unit),
                            "lot": None})
    if "marker" in f:                                     # rule 4 marks
        j = next(j for j, r in enumerate(lot0["rows"]) if r["t"][6] in ("num", "metal", "micro") and
                 not r["result"].startswith("<") and r["loq"] is None and norm(r["result"]) not in ND_WORDS)
        mark = "*" if c.route in SCAN_ROUTES | {"form", "form_mismatch"} or rnd.random() < 0.5 else "sup"
        lot0["rows"][j]["marker"] = mark
        c.notes.append({"text": ("* " if mark == "*" else "a ") + "Result confirmed by retest.", "loq_for": None,
                        "lot": 0, "sup": mark == "sup"})
    if "fail" in f:
        cand = [j for j, r in enumerate(lot0["rows"]) if r["t"][2] in ("max", "range", "min") and
                r["loq"] is None and norm(r["result"]) not in ND_WORDS and r["unit"] == r["t"][4]]
        j = rnd.choice(cand)
        r = lot0["rows"][j]
        t, p = r["t"][2], r["t"][3]
        if t == "max":
            r["result"] = str(round_to(D(p["max"]) * D("1.6"), decimals(p["max"]) + 1))
        elif t == "min":
            r["result"] = str(round_to(D(p["min"]) * D("0.9"), decimals(p["min"])))
        else:
            r["result"] = str(round_to(D(p["max"]) * D("1.03"), decimals(p["max"])))
    if "missing" in f:
        # the fallback skips a marked row: a footnote mark on an empty cell is not a missing result
        j = rnd.choice([j for j, r in enumerate(lot0["rows"]) if r["t"][2] in ("report", "conforms", "absent")]
                       or [next(j for j, r in enumerate(lot0["rows"]) if not r["marker"])])
        lot0["rows"][j]["result"] = None
        if "result_unit" in [k for _, k, _ in c.house["cols"]] or c.house["multi"] == "columns":
            lot0["rows"][j]["unit"] = None               # the unit prints in the result cell, so a blank cell has none
    if "wrap" in f:
        j = next(j for j, r in enumerate(lot0["rows"]) if r["t"][0] == "Appearance")
        for lot in c.lots:
            lot["rows"][j]["result"] = rnd.choice(["White to off-white crystalline powder, odourless",
                                                   "Fine white free-flowing powder with faint odour"])
    if "stamp_retest" in f and lot0["retest"] is None:
        lot0["retest"], lot0["expiry"] = lot0["expiry"], None
    if "expired" in f:                                    # rule 8 receipt date
        lot0["mfg"] = dt.date(2024, rnd.randint(3, 9), rnd.randint(1, 28))
        lot0["retest"] = c.received - dt.timedelta(days=rnd.choice([0, 3, 40]))
        lot0["expiry"] = None
    if "rev_extends" in f:                                # expired lot, revision extends the retest date
        lot0["mfg"] = dt.date(2024, rnd.randint(3, 9), rnd.randint(1, 28))
        lot0["retest"] = c.received - dt.timedelta(days=rnd.randint(5, 60))
        lot0["expiry"] = None
        c.revisions.append({"rev": 2, "lot": 0, "kind": "retest", "value": c.received + dt.timedelta(days=365),
                            "why": "Retest date extended after re-analysis"})
    if "rev_result" in f or "rev_twice" in f:             # rule 5 revisions of a result
        li = len(c.lots) - 1 if len(c.lots) > 1 and rnd.random() < 0.6 else 0
        lot = c.lots[li]
        cand = [j for j, r in enumerate(lot["rows"]) if r["t"][6] in ("num", "metal") and r["loq"] is None and
                norm(r["result"] or "") not in ND_WORDS and not (r["result"] or "<").startswith("<") and
                r["marker"] is None and r["unit"] == r["t"][4]]
        j = rnd.choice(cand)
        r = lot["rows"][j]
        t, p = r["t"][2], r["t"][3]
        good = r["result"]
        if t == "max":
            bad = str(round_to(D(p["max"]) * D("1.4"), max(decimals(p["max"]), 1)))
        elif t == "min":
            bad = str(round_to(D(p["min"]) * D("0.9"), max(decimals(p["min"]), 1)))
        else:
            bad = str(round_to(D(p["max"]) * D("1.02"), max(decimals(p["max"]), 1)))
        # the original prints the failing value; the revision corrects it
        r["result"] = bad
        if "rev_twice" in f:
            mid = str(round_to(D(good) * D("1.1"), max(decimals(good), 1))) if "." in good else good
            c.revisions.append({"rev": 2, "lot": li, "kind": "result", "row": j, "value": mid})
            c.revisions.append({"rev": 3, "lot": li, "kind": "result", "row": j, "value": good})
        else:
            c.revisions.append({"rev": 2, "lot": li, "kind": "result", "row": j, "value": good})
    for lot in c.lots:
        for r in lot["rows"]:
            r["spec_text"] = supplier_spec(r["t"], r["spec_unit"], c.house["spec_style"])

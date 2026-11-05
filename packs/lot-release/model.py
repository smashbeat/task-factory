"""lot-release domain pack: the batch release package model and the policy's truth, with a switch per rule.

A package is one lot of one finished product: the batch record (a workbook), the packing record (a CSV), the label
proof and the finished-product report (PDFs) and one supplier certificate per ingredient lot (PDFs, loose or
attached to emails). Every value is built as data first; the truth comes from this model and never from a file.
`truth(off=...)` answers as an agent would if it ignored the rules in `off`; those answers are the mutants the
builder uses to prove each rule is tested and to attribute failures.
"""
from __future__ import annotations

import calendar
import copy
import datetime as dt
import random
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from taskfactory.forge import coa_doc
from taskfactory.forge.coa_doc import A4, LETTER, MATERIALS, TEST_BY_NAME, TESTS, choice, norm, num

D = Decimal
SUPPLIERS = coa_doc.HOUSES
SCAN_ROUTES = coa_doc.SCAN_ROUTES
FORM_ROUTES = {"form", "form_mismatch"}
MASS = {"mcg": D("0.000001"), "mg": D("0.001"), "g": D(1), "kg": D(1000)}   # grams per unit
REJECTS = ("certificate_fail", "certificate_expired", "supplier_unapproved", "finished_fail")
STATUS_ORDER = ("missing", "unapproved", "expired", "fail", "incomplete")


# ------------------------------------------------------------------ numbers and dates

def convert_mass(v: D, unit: str, to: str) -> D:
    return v * MASS[unit] / MASS[to]


def round_places(v: D, places: int) -> D:
    return v.quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


def fmt(v: D) -> str:
    return format(v, "f")


def add_months(d: dt.date, months: int) -> dt.date:
    """Same day of the month `months` later, or the last day of that month when the day does not exist."""
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def lot_key(s: str) -> str:
    return norm(s).replace("-", "")


def shown(value: D, fmt_code: str) -> D:
    """What a cell with number format `fmt_code` shows: the stored value rounded half up to the format's places."""
    places = len(fmt_code.split(".")[1]) if "." in fmt_code else 0
    return round_places(value, places)


# ------------------------------------------------------------------ catalogue

# label name, per-serving range (low, high, step, unit) and the allergens a carrier may bring
INGREDIENTS = {
    "Ascorbic Acid USP": dict(label="Vitamin C (as Ascorbic Acid)", serving=(100, 1000, 50, "mg"), allergens=[]),
    "Zinc Citrate Trihydrate": dict(label="Zinc Citrate", serving=(10, 60, 5, "mg"), allergens=[]),
    "Magnesium Bisglycinate": dict(label="Magnesium Bisglycinate", serving=(200, 800, 50, "mg"), allergens=[]),
    "Cholecalciferol 100,000 IU/g": dict(label="Vitamin D3 Powder (Cholecalciferol)", serving=(10, 50, 5, "mg"),
                                        allergens=["fish", "soy"]),
    "Ferrous Bisglycinate Chelate": dict(label="Iron (as Ferrous Bisglycinate Chelate)", serving=(20, 100, 10, "mg"),
                                        allergens=[]),
    "Pyridoxine Hydrochloride USP": dict(label="Vitamin B6 (as Pyridoxine HCl)", serving=(5, 50, 5, "mg"), allergens=[]),
    "Calcium Carbonate (Precipitated)": dict(label="Calcium Carbonate", serving=(250, 1000, 50, "mg"),
                                            allergens=["shellfish"]),
}
ALLERGENS = ("fish", "soy", "milk", "shellfish", "tree nuts", "wheat")
# every ingredient's house tests start with these; the rest are drawn
CORE_TESTS = ["Appearance", "Identification (IR)", "Assay (on dried basis)", "Loss on drying", "Lead (Pb)", "Arsenic (As)",
              "Cadmium (Cd)"]
OTHER_TESTS = ["Residue on ignition", "Mercury (Hg)", "Total aerobic microbial count", "Total yeast and mold",
               "Escherichia coli (10 g)", "Salmonella spp. (25 g)", "Particle size (through 80 mesh)", "Bulk density",
               "pH (1% solution)"]

# the finished product's release tests, in the certificate catalogue's tuple form
FP_TESTS = [
    ("Description", ["Appearance"], "report", {}, None,
     choice("White opaque capsules, size 00", "Light tan oval tablets", "Off-white powder-filled capsules"), "text"),
    ("Identification (HPLC)", ["Identity"], "conforms", {}, None, choice("Conforms", "Complies"), "text"),
    ("Assay, label claim", ["Assay (% of label claim)"], "range", {"min": "95.0", "max": "115.0"}, "%",
     num(97.0, 112.0, 1), "num"),
    ("Average fill weight", ["Average weight"], "range", {"min": "480", "max": "520"}, "mg", num(486, 514, 0), "num"),
    ("Disintegration", ["Disintegration time"], "max", {"max": "30"}, "min", choice("12", "15", "18", "22", "26"), "num"),
    ("Loss on drying", ["LOD"], "max", {"max": "5.0"}, "%", num(1.2, 4.3, 1), "num"),
    ("Lead (Pb)", ["Lead", "Pb"], "max", {"max": "0.5"}, "ppm", num(0.02, 0.3, 2), "metal"),
    ("Arsenic (As)", ["Arsenic", "As"], "max", {"max": "0.5"}, "ppm", num(0.02, 0.3, 2), "metal"),
    ("Cadmium (Cd)", ["Cadmium", "Cd"], "max", {"max": "0.3"}, "ppm", num(0.01, 0.2, 2), "metal"),
    ("Mercury (Hg)", ["Mercury", "Hg"], "max", {"max": "0.1"}, "ppm", num(0.005, 0.05, 3), "metal"),
    ("Total aerobic microbial count", ["TAMC"], "max", {"max": "3000"}, "cfu/g", choice("<100", "<10", "250", "600"), "micro"),
    ("Total yeast and mold", ["TYMC"], "max", {"max": "300"}, "cfu/g", choice("<10", "<100", "40"), "micro"),
    ("Escherichia coli (10 g)", ["E. coli (10 g)"], "absent", {}, None, choice("Absent", "Negative"), "text"),
    ("Salmonella spp. (25 g)", ["Salmonella (25 g)"], "absent", {}, None, choice("Absent", "Not detected"), "text"),
]

PRODUCTS = [("Daily Mineral Complex", "Capsules"), ("Immune Defense C-Zn", "Tablets"), ("Mag Calm 400", "Capsules"),
            ("Bone Matrix Plus", "Tablets"), ("Iron Vitality B6", "Capsules"), ("Sunshine D3 Complex", "Capsules"),
            ("Core Multi Mineral", "Tablets")]
CLIENTS = ["Northwind Wellness", "Clearwater Naturals", "Velour Vitality", "Juniper & Sage Co.", "Harborline Health"]
SUPPLIER_ZONE = {"hengxin": "Asia/Shanghai", "nordvik": "Europe/Oslo", "pradesh": "Asia/Kolkata",
                 "bluewater": "America/Los_Angeles"}
SUPPLIER_SHORT = {"hengxin": "Hengxin", "nordvik": "Nordvik", "pradesh": "Pradesh", "bluewater": "Bluewater"}
SUPPLIER_MAIL = {"hengxin": "qc@hengxin-nutrition.example", "nordvik": "qa@nordvik-ingredients.example",
                 "pradesh": "qc.lab@pradeshphytochem.example", "bluewater": "quality@bluewaterbiochem.example"}


def _lab(base, **kw):
    """The manufacturer's own laboratory as a certificate house: the coa drawing laid out like `base`, with the
    house's own words, names and metadata."""
    h = dict(SUPPLIERS[base], layout=base, signer="Released by: QC Release", title="Finished Product Test Report",
             title_caps="FINISHED PRODUCT TEST REPORT")
    h.update(kw)
    return h


STYLES = {
    "sierra": dict(
        name="Sierra Nutraceutical Labs, LLC", short="Sierra", address="1420 Greg Street, Sparks, NV 89431, USA",
        font="Liberation", size=LETTER, date_style="iso", zone="America/Los_Angeles", mail="qa@sierra-nutra.example",
        lot_fmt="SNL-26{n:04d}", lot_word="Lot", sku_fmt="{initials}-{servings}",
        wb=dict(creator="Sierra ERP 9.2", sheets=("Batch", "Dispensing"), totals=True, status_col=False,
                qty_fmt={"kg": "0.000", "g": "0.0", "mg": "0"}),
        csv=dict(total_label="TOTAL", gross=True),
        lab=_lab("bluewater", key="lab-sierra", name="Sierra Nutraceutical Labs QC Laboratory",
                 address="1420 Greg Street, Sparks, NV 89431, USA", font="Liberation", size=LETTER, date_style="iso",
                 lot_label="Lot", mfg_label="Manufactured", retest_label="Retest By", expiry_label="Expires",
                 product_label="Product", extras=[("Release Date", "issue")],
                 meta={"Producer": "ReportLab PDF Library - www.reportlab.com", "Creator": "Sierra LIMS Release 4.0"}),
        meta={"Creator": "Adobe InDesign 19.0 (Macintosh)", "Producer": "Adobe PDF Library 17.0"},
        files=dict(workbook="BR_{lot}.xlsx", csv="PACK_{lot}.csv", label="LBL_{sku}_v{rev}.pdf", report="FPT_{lot}.pdf",
                   cert="{supplier}_CoA_{k}.pdf", email="{supplier}_CoA_{k}.eml", numbered=False),
    ),
    "meridian": dict(
        name="Meridian Contract Formulators Inc.", short="Meridian", address="2200 Argentia Road, Mississauga, ON L5N 1V8, Canada",
        font="Carlito", size=LETTER, date_style="dmy", zone="America/Toronto", mail="quality@meridian-cf.example",
        lot_fmt="MCF2026-{n:03d}", lot_word="Batch", sku_fmt="MCF-{initials}{servings}",
        wb=dict(creator="Microsoft Excel", sheets=("Record", "Dispensing Log"), totals=False, status_col=True,
                qty_fmt={"kg": "0.000", "g": "#,##0.0", "mg": "#,##0"}),
        csv=dict(total_label="Total", gross=True),
        lab=_lab("nordvik", key="lab-meridian", name="Meridian QC Laboratory",
                 address="2200 Argentia Road, Mississauga, ON L5N 1V8, Canada", font="Carlito", size=LETTER, date_style="dmy",
                 lot_label="Batch No.", mfg_label="Manufactured", retest_label="Retest Date", expiry_label="Expiry Date",
                 product_label="Product", extras=[("Issued", "issue")],
                 meta={"Creator": "PScript5.dll Version 5.2.2", "Title": "Microsoft Word - Release Report"}),
        meta={"Creator": "Adobe Illustrator 27.0 (Windows)", "Producer": "Adobe PDF library 17.00"},
        files=dict(numbered=True),
    ),
    "kestrel": dict(
        name="Kestrel Botanicals Ltd.", short="Kestrel", address="Unit 4, Whitehall Industrial Estate, Leeds LS12 5JB, United Kingdom",
        font="DejaVuSerif", size=A4, date_style="dmy", zone="Europe/London", mail="qa@kestrel-botanicals.example",
        lot_fmt="KB-26{n:04d}", lot_word="Batch", sku_fmt="KB{initials}{servings}",
        wb=dict(creator="LibreOffice/7.6.4.1$Linux_X86_64 LibreOffice_project/", sheets=("Batch Record",), totals=True,
                status_col=False, qty_fmt={"kg": "0.000", "g": "0.000", "mg": "0"}),
        csv=dict(total_label="Total", gross=True),
        lab=_lab("nordvik", key="lab-kestrel", name="Kestrel Botanicals Quality Control",
                 address="Unit 4, Whitehall Industrial Estate, Leeds LS12 5JB, United Kingdom", font="DejaVuSerif", size=A4,
                 date_style="dmy", lot_label="Batch", mfg_label="Manufactured", retest_label="Retest", expiry_label="Expiry",
                 product_label="Product", extras=[("Released", "issue")],
                 meta={"Creator": "Writer", "Producer": "LibreOffice 7.6"}),
        meta={"Creator": "Adobe Illustrator 28.0 (Macintosh)", "Producer": "Adobe PDF library 17.00"},
        files=dict(workbook="{lot}-batch.xlsx", csv="{lot}-despatch.csv", label="{lot}-artwork.pdf", report="{lot}-release.pdf",
                   cert="coa-{slug}-{k}.pdf", email="coa-{slug}-{k}.eml", numbered=False),
    ),
}


def fmt_date(d: dt.date, style: str) -> str:
    return coa_doc.fmt_date(d, style)


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower().split(" (")[0]).strip("-").replace("--", "-")


# ------------------------------------------------------------------ the package

class Package:
    """Everything the package's files will say, and the truth derived from it."""

    def __init__(self, pid, style, rnd, n_ingredients, features, route):
        self.id, self.style_key, self.rnd, self.features, self.route = pid, style, rnd, set(features), route
        self.style = STYLES[style]
        product = rnd.choice(PRODUCTS)
        self.product, self.form = product
        self.client = rnd.choice(CLIENTS)
        self.servings = rnd.choice([30, 60, 90])
        self.serving_text = rnd.choice(["1 capsule", "2 capsules", "1 tablet", "2 tablets", "3 capsules"])
        self.shelf_life = rnd.choice([18, 24, 36])
        self.batch_size = rnd.randint(3, 24) * 500
        self.min_yield_pct = rnd.choice([90, 92, 95])
        self.manufactured_on = dt.date(2026, rnd.randint(2, 9), rnd.randint(1, 28))
        self.lot = self.style["lot_fmt"].format(n=rnd.randint(1, 9999))
        self.yield_units = int(self.batch_size * (D(rnd.randint(930, 990)) / 1000))
        self.packed_on = self.manufactured_on + dt.timedelta(days=rnd.randint(3, 12))
        self.label_rev = rnd.randint(1, 3)
        self.ingredients = []
        for k, material in enumerate(rnd.sample(MATERIALS, n_ingredients)):
            cat = INGREDIENTS[material[0]]
            lo, hi, step, unit = cat["serving"]
            per_serving = D(rnd.randrange(lo, hi + 1, step))
            grams = convert_mass(per_serving, unit, "g") * self.servings * self.batch_size
            pb_unit = "kg" if grams >= 1000 else "g"
            places = 3 if pb_unit == "kg" else 1
            per_batch = round_places(convert_mass(grams, "g", pb_unit), places)
            approved = rnd.sample(sorted(SUPPLIERS), rnd.randint(1, 3))
            allergens = [a for a in cat["allergens"] if rnd.random() < 0.5]
            tests = CORE_TESTS + rnd.sample(OTHER_TESTS, rnd.randint(1, 3))
            tests = [n for n in (t[0] for t in TESTS) if n in tests]
            ing = dict(code=f"ING-{k + 1:02d}", material=material, label_name=cat["label"], per_serving=per_serving,
                       ps_unit=unit, per_batch=per_batch, pb_unit=pb_unit, places=places,
                       tolerance_pct=D(rnd.choice(["0.5", "1.0", "2.0"])), approved=approved, allergens=allergens,
                       tests=tests, rows=[])
            self.ingredients.append(ing)
            ing["rows"].append(self._row(ing, rnd.choice(approved), within=True))
        # documents: filled by apply_features
        self.certs: list[dict] = []       # {"cert", "ing", "lots", "supplier", "route", "kind", "email", "void", "name"}
        self.emails: list[dict] = []      # {"date", "frm", "to", "subject", "body", "attachments", "reply_of", "forward_of", "name"}
        self.label = dict(lot=self.lot, expiry=None, amounts=[], allergens=None, revisions=[], outlined=False, name=None)
        self.fp = dict(cert=None, lot=self.lot, name=None, present=True)
        self.packing = dict(lines=[], total=True, total_value=None, lot=self.lot, expiry=None, habit="comma", name=None)
        self.workbook = dict(void_sheet=None, void_rows=False, totals=self.style["wb"]["totals"], totals_lie=None,
                             two_sheets=False, lot=self.lot, name=None)
        self.qty_unit = None               # the unit the dispensing sheet prints quantities in, per ingredient's own unless set
        self.lot_hyphen = False
        self.notes: list[str] = []

    # construction helpers --------------------------------------------
    def _row(self, ing, supplier, within=True, qty=None):
        rnd = self.rnd
        unit = D(1).scaleb(-ing["places"])
        if qty is None:
            tol = ing["per_batch"] * ing["tolerance_pct"] / 100
            span = int(tol / unit)
            qty = ing["per_batch"] + unit * rnd.randint(-span, span)
        return dict(lot=f"{rnd.choice('LBP')}{rnd.randint(100000, 999999)}", supplier=supplier, qty=qty,
                    printed_unit=ing["pb_unit"], stored=None, fmt=None, text=None, void=False, hidden=False, sheet=0)

    def expires_on(self, off=frozenset()) -> dt.date:
        if 6 in off:
            return self.manufactured_on + dt.timedelta(days=30 * self.shelf_life)
        return add_months(self.manufactured_on, self.shelf_life)

    @property
    def spec(self) -> dict:
        return {
            "product": self.product, "client": self.client, "serving": self.serving_text,
            "servings_per_unit": self.servings, "shelf_life_months": self.shelf_life,
            "batch_size_units": self.batch_size, "min_yield_pct": self.min_yield_pct,
            "formula": [{
                "code": i["code"], "material": i["material"][0], "label_name": i["label_name"],
                "per_serving": {"amount": fmt(i["per_serving"]), "unit": i["ps_unit"]},
                "per_batch": {"amount": fmt(i["per_batch"]), "unit": i["pb_unit"]},
                "tolerance_pct": fmt(i["tolerance_pct"]),
                "approved_suppliers": [SUPPLIERS[s]["name"] for s in i["approved"]],
                "allergens": list(i["allergens"]),
                "tests": [{"names": [TEST_BY_NAME[n][0]] + TEST_BY_NAME[n][1],
                           "limit": {"type": TEST_BY_NAME[n][2], **TEST_BY_NAME[n][3]}, "unit": TEST_BY_NAME[n][4]}
                          for n in i["tests"]],
            } for i in self.ingredients],
            "release_tests": [{"names": [t[0]] + t[1], "limit": {"type": t[2], **t[3]}, "unit": t[4]}
                              for t in (self.fp["cert"].tests if self.fp["cert"] else self._fp_tests)],
        }

    # truth -------------------------------------------------------------
    def _standing(self, off):
        """The certificate documents that count, after voids and supersession (rule 7)."""
        docs = list(self.certs)
        if 7 not in off:
            docs = [d for d in docs if not d["void"]]
        groups: dict[tuple, list] = {}
        for d in docs:
            for lot in d["lots"]:
                groups.setdefault((d["supplier"], d["cert"].material[0], lot_key(lot)), []).append(d)
        standing = set()
        for key, ds in groups.items():
            if len(ds) == 1:
                standing.add(id(ds[0]))
                continue
            if 7 in off:
                best = min(ds, key=self._file_of)
            else:
                best = max(ds, key=lambda d: self._cert_date(d) or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
            standing.add(id(best))
        return [d for d in docs if id(d) in standing]

    def _file_of(self, doc) -> str:
        """The name of the file that holds the certificate: its own, or its email's (the forward's for an embedded one)."""
        if doc["email"] is None:
            return doc["name"] or ""
        e = self.emails[doc["email"]]
        if e["embedded"]:
            fwd = next((x for x in self.emails if x["forward_of"] == doc["email"]), None)
            return (fwd or e)["name"] or ""
        return e["name"] or ""

    def _cert_date(self, doc):
        if doc["email"] is None:
            return None
        return self.emails[doc["email"]]["date"]

    def _find_cert(self, standing, ing, lot):
        for d in standing:
            if d["supplier"] == lot["supplier"] and d["cert"].material[0] == ing["material"][0] \
                    and any(lot_key(l) == lot_key(lot["lot"]) for l in d["lots"]):
                return d
        return None

    def _row_value(self, ing, row, off):
        """What the dispensing row contributes, in the per-batch unit (rule 4), from what the cell shows (rule 2)."""
        if row["text"] is not None:
            printed = D(row["text"].replace(",", ""))
        elif row["stored"] is not None:
            printed = shown(row["stored"], row["fmt"]) if 2 not in off else row["stored"]
        else:
            printed = row["qty_printed"]
        if 4 in off:
            return printed
        return round_places(convert_mass(printed, row["printed_unit"], ing["pb_unit"]), ing["places"])

    def _lots(self, ing, off):
        rows = [r for r in ing["rows"] if not r["void"]] if 7 not in off else list(ing["rows"])
        if 7 in off and self.workbook["void_sheet"] is not None:
            # void marks ignored: the voided first draft sits first in tab order and is read instead
            rows = [r for code, r in self.workbook["void_sheet"]["rows"] if code == ing["code"]]
        if 7 in off:
            # void marks ignored: a voided row replaces the row it was reissued as
            seen = set()
            kept = []
            for r in rows:
                if lot_key(r["lot"]) in seen and r.get("twin"):
                    continue
                seen.add(lot_key(r["lot"]))
                kept.append(r)
            rows = kept
        lots = []
        for r in rows:
            for lot in lots:
                if lot_key(lot["lot"]) == lot_key(r["lot"]) and lot["supplier"] == r["supplier"]:
                    lot["rows"].append(r)
                    break
            else:
                lots.append(dict(lot=r["lot"], supplier=r["supplier"], rows=[r]))
        return lots

    def truth(self, off=frozenset()) -> dict:
        m = self.manufactured_on
        expires = self.expires_on(off)
        findings: list[str] = []
        rows_out = []
        standing = self._standing(off)
        for ing in self.ingredients:
            code = ing["code"]
            spec = {"tests": [{"names": [TEST_BY_NAME[n][0]] + TEST_BY_NAME[n][1],
                               "limit": {"type": TEST_BY_NAME[n][2], **TEST_BY_NAME[n][3]}, "unit": TEST_BY_NAME[n][4]}
                              for n in ing["tests"]]}
            lots = self._lots(ing, off)
            if not lots:
                findings.append(f"ingredient_missing:{code}")
                rows_out.append({"code": code, "supplier": None, "lot": None, "dispensed": None, "certificate": "missing"})
                continue
            total = D(0)
            for lot in lots:
                q = sum((self._row_value(ing, r, off) for r in lot["rows"]), D(0))
                total += q
                supplier_name = SUPPLIERS[lot["supplier"]]["name"]
                status = []
                doc = self._find_cert(standing, ing, lot)
                if doc is None:
                    status.append("missing")
                if lot["supplier"] not in ing["approved"]:
                    status.append("unapproved")
                if doc is not None:
                    idx = next(i for i, l in enumerate(doc["lots"]) if lot_key(l) == lot_key(lot["lot"]))
                    entry = doc["cert"].entries()[idx]
                    d = entry["retest_date"] or entry["expiry_date"]
                    d = dt.date.fromisoformat(d) if d else None
                    usable = d is None or (d > self.packed_on if 6 in off else d >= m)
                    if not usable:
                        status.append("expired")
                    rs = coa_doc.results_status(spec, entry)
                    if rs != "ok":
                        status.append(rs)
                if 5 in off:
                    status = [s for s in status if s not in ("missing", "fail", "incomplete")]
                for s in status:
                    findings.append(f"{'supplier_unapproved' if s == 'unapproved' else 'certificate_' + s}:{code}:{lot['lot']}")
                rows_out.append({"code": code, "supplier": supplier_name, "lot": lot["lot"], "dispensed": fmt(q),
                                 "certificate": next((s for s in STATUS_ORDER if s in status), "ok")})
            tol = ing["per_batch"] * ing["tolerance_pct"] / 100
            if abs(total - ing["per_batch"]) > tol:
                findings.append(f"quantity:{code}")
        # label (rule 8), with its revisions (rule 7)
        lab = self.label
        label_lot, label_expiry = lab["lot"], lab["expiry"]
        amounts = {a["code"]: a for a in lab["amounts"]}
        if 7 not in off:
            for rev in sorted(lab["revisions"], key=lambda r: r["rev"]):
                if rev["field"] == "lot":
                    label_lot = rev["value"]
                elif rev["field"] == "expiry":
                    label_expiry = rev["value"]
                else:
                    amounts[rev["field"]] = dict(amounts.get(rev["field"], {"code": rev["field"]}),
                                                 amount=rev["value"][0], unit=rev["value"][1])
        if lot_key(label_lot) != lot_key(self.lot):
            findings.append("label_lot")
        if label_expiry != expires:
            findings.append("label_expiry")
        for ing in self.ingredients:
            a = amounts.get(ing["code"])
            if a is None:
                findings.append(f"label_amount:{ing['code']}")
                continue
            if 8 in off:
                same = a["amount"] == ing["per_serving"]
            else:
                same = convert_mass(a["amount"], a["unit"], ing["ps_unit"]) == ing["per_serving"]
            if not same:
                findings.append(f"label_amount:{ing['code']}")
        want = sorted({a for i in self.ingredients for a in i["allergens"]})
        have = sorted(lab["allergens"]) if lab["allergens"] else []
        if 8 not in off and have != want:
            findings.append("label_allergen")
        # finished-product report (rule 9)
        fp = self.fp
        if not fp["present"] or (fp["cert"] is not None and lot_key(fp["lot"]) != lot_key(self.lot)):
            finished = "missing"
        elif 9 in off:
            finished = "ok"
        else:
            finished = coa_doc.results_status(self.spec_release_tests(), fp["cert"].entries()[0])
        if finished != "ok":
            findings.append(f"finished_{finished}")
        # packing and yield (rule 10)
        pk = self.packing
        units = sum(l["cases"] * l["upc"] + l["loose"] for l in pk["lines"])
        if 10 in off and pk["total"] and pk["total_value"] is not None:
            units = pk["total_value"]
        if units != self.yield_units:
            findings.append("packing_units")
        if lot_key(pk["lot"]) != lot_key(self.lot):
            findings.append("packing_lot")
        if pk["expiry"] != expires:
            findings.append("packing_expiry")
        if 10 not in off and self.yield_units * 100 < self.min_yield_pct * self.batch_size:
            findings.append("yield_low")
        findings = sorted(set(findings))
        if 11 in off:
            decision = "hold" if findings else "released"
        elif any(f.split(":")[0] in REJECTS for f in findings):
            decision = "rejected"
        elif findings:
            decision = "hold"
        else:
            decision = "released"
        return {"product": self.product, "lot": self.lot, "manufactured_on": m.isoformat(),
                "expires_on": expires.isoformat(), "yield": self.yield_units, "ingredients": rows_out,
                "label": {"lot": label_lot, "expiry": label_expiry.isoformat() if label_expiry else None},
                "finished": finished, "packing": {"units": sum(l["cases"] * l["upc"] + l["loose"] for l in pk["lines"])},
                "findings": findings, "decision": decision}

    def spec_release_tests(self):
        return {"tests": self.spec["release_tests"]}

    # inventory ---------------------------------------------------------
    @property
    def files(self) -> list[dict]:
        out = [dict(name=self.workbook["name"], kind="workbook"), dict(name=self.packing["name"], kind="csv"),
               dict(name=self.label["name"], kind="label")]
        if self.fp["present"]:
            out.append(dict(name=self.fp["name"], kind="report"))
        for i, d in enumerate(self.certs):
            if d["email"] is None:
                out.append(dict(name=d["name"], kind="cert", cert=i))
        for i, e in enumerate(self.emails):
            if e["name"] is not None:
                out.append(dict(name=e["name"], kind="email", email=i))
        return out

    def pdf_pages(self) -> int:
        n = 1 + (1 if self.fp["present"] else 0)
        for d in self.certs:
            n += 2 if len(d["lots"]) > 1 and d["cert"].house["multi"] == "pages" else 1
        return n


# ------------------------------------------------------------------ features

def _cert(p: Package, ing, lots, supplier, features=(), route=None, void=False):
    """A certificate document for `lots` of an ingredient's material from `supplier`, through `route`."""
    rnd = random.Random(p.rnd.random())
    route = route or p.route
    c = coa_doc.Cert(f"{p.id}-c{len(p.certs)}", supplier, rnd, len(lots), set(features), route,
                     material=ing["material"], lot_numbers=list(lots), received=p.manufactured_on, tests=ing["tests"])
    coa_doc.apply_features(c)
    doc = dict(cert=c, ing=p.ingredients.index(ing) if ing in p.ingredients else None, lots=list(lots), supplier=supplier,
               route=route, email=None, void=void, name=None, k=len(p.certs))
    p.certs.append(doc)
    return doc


def _email(p: Package, doc_or_docs, date=None, reply_of=None, forward_of=None, body=None, embedded=False):
    docs = doc_or_docs if isinstance(doc_or_docs, list) else [doc_or_docs]
    first = docs[0]
    sup = first["supplier"]
    if forward_of is not None:
        inner = p.emails[forward_of]
        frm, to = f"Purchasing <buy@{p.style['mail'].split('@')[1]}>", p.style["mail"]
        subject = "Fwd: " + inner["subject"]
        date = date or inner["date"].astimezone(ZoneInfo(p.style["zone"])) + dt.timedelta(hours=p.rnd.randint(3, 40))
        body = body or "Forwarding the supplier's certificate for the release file.\n"
        att = []
    else:
        frm = f"{SUPPLIERS[sup]['name']} QC <{SUPPLIER_MAIL[sup]}>"
        to = p.style["mail"]
        lots = ", ".join(l for d in docs for l in d["lots"])
        subject = f"{'Re: ' if reply_of is not None else ''}Certificate of Analysis, {first['cert'].material[0]}, lot {lots}"
        if date is None:
            issue = first["cert"].issue
            date = dt.datetime(issue.year, issue.month, issue.day, p.rnd.randint(8, 17), p.rnd.choice([0, 15, 30, 45]),
                               tzinfo=ZoneInfo(SUPPLIER_ZONE[sup]))
        body = body or f"Dear QA team,\n\nPlease find attached the certificate of analysis for {first['cert'].material[0]}, lot {lots}.\n\nBest regards,\nQC Department\n{SUPPLIERS[sup]['name']}\n"
        att = [p.certs.index(d) for d in docs]
    e = dict(date=date, frm=frm, to=to, subject=subject, body=body, attachments=att, reply_of=reply_of,
             forward_of=forward_of, name=None, embedded=embedded)
    p.emails.append(e)
    idx = len(p.emails) - 1
    for d in docs:
        d["email"] = idx
    return idx


def _pick_ing(p: Package, used: set, need_rows=True):
    """The next ingredient a feature lands on, spreading features over the formula."""
    for i, ing in enumerate(p.ingredients):
        if i not in used and (ing["rows"] or not need_rows):
            used.add(i)
            return ing
    for i, ing in enumerate(p.ingredients):
        if ing["rows"] or not need_rows:
            return ing
    return p.ingredients[0]


def apply_features(p: Package):
    rnd, f = p.rnd, p.features
    used: set[int] = set()
    # ---- the formula's dispensing rows (rule 4)
    if "two_lots_dispensed" in f:
        ing = _pick_ing(p, used)
        r = ing["rows"][0]
        split = round_places(r["qty"] * D(rnd.choice(["0.4", "0.55", "0.7"])), ing["places"])
        second = p._row(ing, rnd.choice(ing["approved"]), qty=r["qty"] - split)
        r["qty"] = split
        ing["rows"].append(second)
    if "ingredient_missing" in f:
        ing = p.ingredients[-1] if len(p.ingredients) > 1 else p.ingredients[0]
        used.add(p.ingredients.index(ing))
        ing["rows"] = []
    if "qty_tolerance" in f:
        ing = _pick_ing(p, used)
        unit = D(1).scaleb(-ing["places"])
        tol = ing["per_batch"] * ing["tolerance_pct"] / 100
        edge = round_places(tol, ing["places"])            # the tolerance at the per-batch places
        sign = rnd.choice([-1, 1])
        if rnd.random() < 0.5:
            target = ing["per_batch"] + sign * edge          # exactly on the edge: within
            p.notes.append(f"{ing['code']} on the tolerance")
        else:
            target = ing["per_batch"] + sign * (edge + unit)  # one unit past: out
            p.notes.append(f"{ing['code']} one unit past the tolerance")
        others = sum((r["qty"] for r in ing["rows"][1:]), D(0))
        ing["rows"][0]["qty"] = target - others
    if "cell_format" in f:
        # the sheet shows a value on the edge; the stored number is a hair past it, so only the format decides
        ing = _pick_ing(p, used)
        unit = D(1).scaleb(-ing["places"])
        tol = round_places(ing["per_batch"] * ing["tolerance_pct"] / 100, ing["places"])
        r = ing["rows"][0]
        others = sum((x["qty"] for x in ing["rows"][1:]), D(0))
        r["qty"] = ing["per_batch"] + tol - others          # what the cell shows: exactly on the edge, within
        r["stored"] = r["qty"] + unit * D("0.6")           # stored past the edge: rounded at the places it is out
        r["edge"] = True                                    # shown with one place fewer than the per-batch amount
        p.notes.append(f"{ing['code']} stored {fmt(r['stored'])}, shown {fmt(r['qty'])}")
    if "qty_unit" in f:
        p.qty_unit = rnd.choice(["kg", "mg"]) if all(i["pb_unit"] == "g" for i in p.ingredients) else \
            rnd.choice(["g", "mg"]) if all(i["pb_unit"] == "kg" for i in p.ingredients) else rnd.choice(["kg", "g", "mg"])
    for ing in p.ingredients:
        for r in ing["rows"]:
            r["printed_unit"] = ing["pb_unit"] if r.get("edge") else (p.qty_unit or ing["pb_unit"])
            r["qty_printed"] = convert_mass(r["qty"], ing["pb_unit"], r["printed_unit"])
            if r["stored"] is not None:
                r["stored"] = convert_mass(r["stored"], ing["pb_unit"], r["printed_unit"])
            r["fmt"] = p.style["wb"]["qty_fmt"][r["printed_unit"]]
            if r["printed_unit"] == "kg" and ing["pb_unit"] == "g":
                r["fmt"] = "0.000000"
            if r["printed_unit"] == "mg":
                r["fmt"] = "#,##0" if ing["pb_unit"] == "kg" else "#,##0.0"
            if r.get("edge"):
                r["fmt"] = "0." + "0" * (ing["places"] - 1) if ing["places"] > 1 else "0"
            if r["stored"] is None:
                r["stored"] = r["qty_printed"]
    if "text_number" in f:
        # the largest quantity, in a unit that gives it a thousands separator
        ing, r = max(((i, x) for i in p.ingredients for x in i["rows"] if not x["void"]), key=lambda t: t[1]["qty_printed"])
        if r["qty_printed"] < 1000 and r["printed_unit"] in ("kg", "g"):
            r["printed_unit"] = {"kg": "g", "g": "mg"}[r["printed_unit"]]
            r["qty_printed"] = convert_mass(r["qty"], ing["pb_unit"], r["printed_unit"])
            r["stored"] = r["qty_printed"]
            r["fmt"] = _base_fmt_for(p, ing, r["printed_unit"])
        whole, _, frac = fmt(r["qty_printed"]).partition(".")
        r["text"] = f"{int(whole):,}" + (f".{frac}" if frac else "")
    if "hidden_row" in f:
        ing = p.ingredients[-1] if p.ingredients[-1]["rows"] else p.ingredients[0]
        ing["rows"][-1]["hidden"] = True
    if "two_sheets" in f:
        p.workbook["two_sheets"] = True
        for ing in p.ingredients[len(p.ingredients) // 2:]:
            for r in ing["rows"]:
                r["sheet"] = 1
    if "void_document" in f:
        variant = rnd.choice(["sheet", "rows", "certificate"])
        p.workbook["void_variant"] = variant
        if variant == "sheet":
            # a first draft of the log, voided, with quantities out of tolerance
            draft = []
            for ing in p.ingredients:
                for r in ing["rows"]:
                    d = dict(r, qty_printed=r["qty_printed"] * D("1.08"), stored=r["stored"] * D("1.08"), text=None)
                    draft.append((ing["code"], d))
            p.workbook["void_sheet"] = dict(hidden=rnd.random() < 0.5, rows=draft)
        elif variant == "rows":
            ing = _pick_ing(p, used)
            r = ing["rows"][0]
            v = dict(r, qty_printed=r["qty_printed"] * D("1.08"), stored=r["stored"] * D("1.08"), text=None, void=True, twin=False)
            r["twin"] = True
            ing["rows"].insert(0, v)
            p.workbook["void_rows"] = True
    if "total_lies" in f:
        where = rnd.choice(["workbook", "csv"]) if p.style["wb"]["totals"] else "csv"
        p.workbook["totals_lie"] = where
    if "lot_hyphen" in f:
        p.lot_hyphen = True
    # ---- certificates (rules 5, 6, 7) and how they arrived (rules 1, 2)
    extra_coa = {"coa_fail": {"fail"}, "coa_incomplete": {"missing"},
                 "coa_conversion": {rnd.choice(["units", "nd_loq_note"])}, "coa_revision": {"rev_result", "rev_block"},
                 "stamp_lot": {"stamp_lot"}, "annot_correction": {"annot_correction"}, "watermark": {"watermark"}}
    lot_targets = [(ing, r) for ing in p.ingredients for r in ing["rows"] if not r["void"]]
    per_lot_features: dict[int, set] = {i: set() for i in range(len(lot_targets))}
    routes: dict[int, str] = {}
    k = 0
    for name, feats in extra_coa.items():
        if name in f and lot_targets:
            per_lot_features[k % len(lot_targets)] |= feats
            k += 1
    if "member_scan" in f and lot_targets:
        routes[k % len(lot_targets)] = rnd.choice(sorted(SCAN_ROUTES))
        k += 1
    if "member_outlined" in f and lot_targets:
        routes[k % len(lot_targets)] = "outlined"
        k += 1
    missing_idx = unapproved_idx = expired_idx = None
    if "coa_missing" in f and lot_targets:
        missing_idx = k % len(lot_targets); k += 1
    if "unapproved_supplier" in f and lot_targets:
        unapproved_idx = k % len(lot_targets); k += 1
        ing, r = lot_targets[unapproved_idx]
        others = [s for s in SUPPLIERS if s not in ing["approved"]]
        if others:
            r["supplier"] = rnd.choice(others)
        else:
            ing["approved"] = [s for s in ing["approved"] if s != r["supplier"]] or ing["approved"][:1]
            if r["supplier"] in ing["approved"]:
                r["supplier"] = rnd.choice([s for s in SUPPLIERS if s not in ing["approved"]])
    if "coa_expired" in f and lot_targets:
        expired_idx = k % len(lot_targets); k += 1
    two_lots_idx = None
    if "coa_two_lots" in f and lot_targets:
        two_lots_idx = k % len(lot_targets); k += 1
    supersede_idx = None
    if "eml_reply_supersedes" in f and lot_targets:
        supersede_idx = k % len(lot_targets); k += 1
    void_cert_idx = None
    if p.workbook.get("void_variant") == "certificate" and lot_targets:
        void_cert_idx = k % len(lot_targets); k += 1
    docs_by_lot = {}
    for i, (ing, r) in enumerate(lot_targets):
        if i == missing_idx:
            continue
        lots = [r["lot"]]
        if i == two_lots_idx:
            other = f"{r['lot'][0]}{rnd.randint(100000, 999999)}"
            lots = [other, r["lot"]] if rnd.random() < 0.5 else [r["lot"], other]
        feats = set(per_lot_features[i])
        if i == supersede_idx:
            # the first certificate is wrong and corrected by a reply, or right and replaced by a failing one
            first_fails = rnd.random() < 0.5
            a = _cert(p, ing, lots, r["supplier"], feats | ({"fail"} if first_fails else set()), routes.get(i))
            b = _cert(p, ing, lots, r["supplier"], feats | (set() if first_fails else {"fail"}), routes.get(i))
            ea = _email(p, a)
            delta = dt.timedelta(days=rnd.randint(1, 4), hours=rnd.randint(0, 9))
            if rnd.random() < 0.4:
                # the reply's clock reads earlier: only the zone makes it later
                later = p.emails[ea]["date"] + dt.timedelta(hours=2)
                zone = ZoneInfo(rnd.choice(["America/Los_Angeles", "America/New_York", "Pacific/Honolulu"]))
                later = later.astimezone(zone)
                p.notes.append("reply dated later only by its zone")
            else:
                later = p.emails[ea]["date"] + delta
            _email(p, b, date=later, reply_of=ea, body="Please disregard the earlier certificate; the corrected one is attached.\n")
            docs_by_lot[i] = b
            continue
        doc = _cert(p, ing, lots, r["supplier"], feats, routes.get(i))
        docs_by_lot[i] = doc
        if i == expired_idx:
            lot0 = doc["cert"].lots[lots.index(r["lot"])]
            equal = rnd.random() < 0.4
            d = p.manufactured_on if equal else p.manufactured_on - dt.timedelta(days=rnd.randint(1, 120))
            if lot0["retest"] is not None:
                lot0["retest"] = d
            else:
                lot0["expiry"] = d
            p.notes.append("retest date equal to the manufacturing date, usable" if equal else "certificate expired")
        if i == void_cert_idx:
            v = _cert(p, ing, lots, r["supplier"], feats | {"fail"}, routes.get(i), void=True)
            v["k"] = -1   # named to sort first, so the mutant that ignores void marks takes it
    if "extra_certificate" in f:
        ing = p.ingredients[0]
        sup = ing["rows"][0]["supplier"] if ing["rows"] else rnd.choice(ing["approved"])
        extra = _cert(p, ing, [f"{rnd.choice('LBP')}{rnd.randint(100000, 999999)}"], sup)
        extra["extra"] = True
    # how each certificate arrived: by email unless drawn loose
    pending = [d for d in p.certs if d["email"] is None and not d["void"]]
    if "eml_two_attachments" in f and len(pending) >= 2:
        a, b = pending[0], pending[1]
        _email(p, [a, b])
        pending = pending[2:]
    for d in pending:
        if d.get("extra") and rnd.random() < 0.5:
            continue
        if rnd.random() < 0.72 or "eml_forwarded" in f or "eml_body_lies" in f:
            _email(p, d)
    if "eml_forwarded" in f:
        # a message somebody replied to stays a file of its own; the forward wraps another one (a reply will do)
        replied = {e["reply_of"] for e in p.emails if e["reply_of"] is not None}
        cand = [i for i, e in enumerate(p.emails) if e["forward_of"] is None and e["attachments"] and i not in replied]
        if cand:
            inner = cand[-1]
            p.emails[inner]["embedded"] = True
            _email(p, [p.certs[j] for j in p.emails[inner]["attachments"]], forward_of=inner)
            for j in p.emails[inner]["attachments"]:
                p.certs[j]["email"] = inner      # the certificate's date is the inner message's
    if "eml_body_lies" in f:
        cand = [e for e in p.emails if e["attachments"] and e["forward_of"] is None]
        if cand:
            e = cand[-1]
            d = p.certs[e["attachments"][0]]
            fake = f"{d['lots'][0][0]}{rnd.randint(100000, 999999)}"
            e["body"] = (f"Dear QA team,\n\nAttached is the certificate for {d['cert'].material[0]}, lot {fake}. "
                         f"Assay {rnd.choice(['97.2', '96.8', '98.1'])} %, all heavy metals within limits.\n\nBest regards,\nQC Department\n")
            p.notes.append(f"email body names lot {fake}")
    # ---- label (rule 8) and its revisions (rule 7)
    lab = p.label
    lab["expiry"] = p.expires_on()
    lab["outlined"] = "label_outlined" in f
    for ing in p.ingredients:
        lab["amounts"].append(dict(code=ing["code"], label_name=ing["label_name"], amount=ing["per_serving"], unit=ing["ps_unit"]))
    allergens = sorted({a for i in p.ingredients for a in i["allergens"]})
    if "allergen_wrong" in f:
        if allergens and rnd.random() < 0.5:
            allergens = allergens[1:]
            p.notes.append("label omits an allergen")
        else:
            if not allergens:
                # the formula must carry one for the label to miss it or to add a second
                ing = p.ingredients[0]
                ing["allergens"] = [rnd.choice(ALLERGENS[:3])]
                allergens = list(ing["allergens"])
                if rnd.random() < 0.5:
                    allergens = []
                    p.notes.append("label omits the only allergen")
            if allergens == sorted({a for i in p.ingredients for a in i["allergens"]}):
                allergens = sorted(allergens + [rnd.choice([a for a in ALLERGENS if a not in allergens])])
                p.notes.append("label names an allergen the formula has not")
    lab["allergens"] = allergens or None
    if "label_mcg" in f:
        a = next((a for a in lab["amounts"] if a["unit"] == "mg"), lab["amounts"][0])
        if a["unit"] == "mg":
            a["amount"], a["unit"] = a["amount"] * 1000, "mcg"
        else:
            a["amount"], a["unit"] = a["amount"] / 1000, "mg"
    if "label_amount" in f:
        a = lab["amounts"][-1]
        if rnd.random() < 0.5 and len(lab["amounts"]) > 1:
            lab["amounts"].remove(a)
            p.notes.append(f"label omits {a['code']}")
        else:
            a["amount"] = round_places(a["amount"] * D(rnd.choice(["1.1", "0.9", "2"])), 0) or a["amount"] + 1
            p.notes.append(f"label amount wrong for {a['code']}")
    if "label_expiry_wrong" in f:
        lab["expiry"] = rnd.choice([add_months(p.manufactured_on, p.shelf_life + 1),
                                    p.manufactured_on + dt.timedelta(days=30 * p.shelf_life)])
        if lab["expiry"] == p.expires_on():
            lab["expiry"] = add_months(p.manufactured_on, p.shelf_life - 1)
    if "lot_mismatch" in f:
        other = p.style["lot_fmt"].format(n=(int("".join(ch for ch in p.lot if ch.isdigit())[-3:]) + 1) % 1000 or 1)
        if rnd.random() < 0.5:
            lab["lot"] = other
            p.notes.append("label prints another lot")
        else:
            p.packing["lot"] = other
            p.notes.append("packing record prints another lot")
    if "label_revision" in f:
        # the panel prints an old value; the revision table's highest revision gives the one that stands
        if rnd.random() < 0.5:
            wrong = p.style["lot_fmt"].format(n=(int("".join(ch for ch in p.lot if ch.isdigit())[-4:]) + 7) % 10000 or 1)
            lab["revisions"] = [dict(rev=1, field="lot", value=wrong), dict(rev=2, field="lot", value=lab["lot"])]
            lab["lot"] = wrong
        else:
            a = lab["amounts"][0]
            right = (a["amount"], a["unit"])
            a["amount"] = a["amount"] + D(rnd.choice([5, 10, 50]))
            lab["revisions"] = [dict(rev=1, field=a["code"], value=(a["amount"], a["unit"])),
                                dict(rev=2, field=a["code"], value=right)]
        p.label_rev = 2
    # ---- finished-product report (rule 9)
    fp = p.fp
    p._fp_tests = [t for t in FP_TESTS]
    feats = {"fail"} if "fp_fail" in f else {"missing"} if "fp_incomplete" in f else set()
    if "fp_missing" in f and rnd.random() < 0.5:
        fp["present"] = False
        fp["cert"] = coa_doc.Cert(f"{p.id}-fp", p.style["lab"], random.Random(rnd.random()), 1, set(), p.route,
                                  catalogue=FP_TESTS, material=(p.product, p.form), lot_numbers=[p.lot],
                                  received=p.manufactured_on)
        coa_doc.apply_features(fp["cert"])
        p.notes.append("no finished-product report")
    else:
        lot = p.lot
        if "fp_missing" in f:
            lot = p.style["lot_fmt"].format(n=(int("".join(ch for ch in p.lot if ch.isdigit())[-4:]) + 3) % 10000 or 1)
            p.notes.append("finished-product report for another lot")
        fp["lot"] = lot
        fp["cert"] = coa_doc.Cert(f"{p.id}-fp", p.style["lab"], random.Random(rnd.random()), 1, feats, p.route,
                                  catalogue=FP_TESTS, material=(p.product, p.form), lot_numbers=[lot],
                                  received=p.manufactured_on)
        coa_doc.apply_features(fp["cert"])
    # ---- packing record (rule 10)
    if "yield_low" in f:
        p.yield_units = int(p.batch_size * (D(rnd.randint(800, p.min_yield_pct * 10 - 5)) / 1000))
    pk = p.packing
    pk["expiry"] = p.expires_on()
    upc = rnd.choice([12, 24, 48])
    n_lines = rnd.randint(1, 3)
    cases_total, loose = divmod(p.yield_units, upc)
    cuts = sorted(rnd.sample(range(1, cases_total), n_lines - 1)) if n_lines > 1 and cases_total > n_lines else []
    bounds = [0] + cuts + [cases_total]
    for i in range(len(bounds) - 1):
        pk["lines"].append(dict(pallet=i + 1, cases=bounds[i + 1] - bounds[i], upc=upc, loose=0,
                                gross=round_places(D(bounds[i + 1] - bounds[i]) * D(upc) * D("0.0412") + D("18.5"), 1)))
    pk["lines"][-1]["loose"] = loose
    if "packing_mismatch" in f:
        pk["lines"][0]["cases"] += rnd.choice([-3, -2, -1, 1, 2])
    pk["total"] = "packing_math" not in f
    pk["total_value"] = sum(l["cases"] * l["upc"] + l["loose"] for l in pk["lines"])
    if p.workbook["totals_lie"] == "csv" and pk["total"]:
        pk["total_value"] = p.yield_units if pk["total_value"] != p.yield_units else p.yield_units + rnd.choice([12, 24, 48])
        p.notes.append("CSV total line lies")
    if "csv_semicolon" in f:
        pk["habit"] = "semicolon"
    # ---- decision (rule 11)
    if "reject_and_hold" in f:
        # one finding of each class, whatever else the package carries
        t = p.truth()
        if not any(x.split(":")[0] in REJECTS for x in t["findings"]):
            ing = p.ingredients[0]
            lot = ing["rows"][0] if ing["rows"] else None
            if lot is not None:
                doc = next((d for d in p.certs if d["ing"] == 0 and lot["lot"] in d["lots"] and not d["void"]), None)
                if doc is not None:
                    _fail_a_result(doc["cert"])
        t = p.truth()
        if all(x.split(":")[0] in REJECTS for x in t["findings"]):
            if pk["lines"]:
                pk["lines"][0]["cases"] += 1
                pk["total_value"] = sum(l["cases"] * l["upc"] + l["loose"] for l in pk["lines"])
    # ---- file names
    _name_files(p)
    return p


def _base_fmt_for(p: Package, ing, unit: str) -> str:
    """The number format a quantity in `unit` takes in this style's workbook."""
    f = p.style["wb"]["qty_fmt"][unit]
    if unit == "kg" and ing["pb_unit"] == "g":
        f = "0.000000"
    if unit == "mg":
        f = "#,##0" if ing["pb_unit"] == "kg" else "#,##0.0"
    return f


def _fail_a_result(cert):
    """Turn one numeric result of the first lot into a failing one, as the coa `fail` feature does."""
    lot = cert.lots[0]
    for r in lot["rows"]:
        t, prm = r["t"][2], r["t"][3]
        if t == "max" and r["result"] and not r["result"].startswith("<") and norm(r["result"]) not in coa_doc.ND_WORDS \
                and r["unit"] == r["t"][4] and r["loq"] is None:
            r["result"] = str(coa_doc.round_to(D(prm["max"]) * D("1.6"), coa_doc.decimals(prm["max"]) + 1))
            r["spec_text"] = coa_doc.supplier_spec(r["t"], r["spec_unit"], cert.house["spec_style"])
            return


def _name_files(p: Package):
    st = p.style
    initials = "".join(w[0] for w in p.product.split() if w[0].isalpha())[:3].upper()
    sku = st["sku_fmt"].format(initials=initials, servings=p.servings)
    lot_in_name = p.lot.replace("/", "-")
    if st["files"].get("numbered"):
        kinds = [("workbook", "xlsx"), ("csv", "csv"), ("label", "pdf")] + ([("report", "pdf")] if p.fp["present"] else [])
        kinds += [("cert", "pdf", i) for i, d in enumerate(p.certs) if d["email"] is None]
        kinds += [("email", "eml", i) for i, e in enumerate(p.emails) if not e["embedded"]]
        order = list(range(len(kinds)))
        p.rnd.shuffle(order)
        for n, idx in enumerate(order, start=1):
            kind = kinds[idx]
            name = f"doc{n:02d}.{kind[1]}"
            if kind[0] == "workbook":
                p.workbook["name"] = name
            elif kind[0] == "csv":
                p.packing["name"] = name
            elif kind[0] == "label":
                p.label["name"] = name
            elif kind[0] == "report":
                p.fp["name"] = name
            elif kind[0] == "cert":
                p.certs[kind[2]]["name"] = name
            else:
                p.emails[kind[2]]["name"] = name
        return
    p.workbook["name"] = st["files"]["workbook"].format(lot=lot_in_name)
    p.packing["name"] = st["files"]["csv"].format(lot=lot_in_name)
    p.label["name"] = st["files"]["label"].format(sku=sku, rev=p.label_rev, lot=lot_in_name)
    if p.fp["present"]:
        p.fp["name"] = st["files"]["report"].format(lot=lot_in_name)
    taken: set[str] = set()

    def unique(pattern, doc):
        k = 1
        while True:
            name = pattern.format(supplier=SUPPLIER_SHORT[doc["supplier"]], slug=_slug(doc["cert"].material[0]), k=k)
            if name not in taken:
                taken.add(name)
                return name
            k += 1

    for d in sorted(p.certs, key=lambda d: d["k"]):
        if d["email"] is None:
            d["name"] = unique(st["files"]["cert"], d)
    for e in p.emails:
        if e["embedded"]:
            continue
        docs = [p.certs[i] for i in e["attachments"]] or [p.certs[i] for i in p.emails[e["forward_of"]]["attachments"]]
        e["name"] = unique(st["files"]["email"], docs[0])


def min_units(features: set) -> int:
    """The fewest ingredients a composition needs."""
    need = 1
    if features & {"eml_two_attachments", "ingredient_missing", "hidden_row", "two_sheets"}:
        need = 2
    return need

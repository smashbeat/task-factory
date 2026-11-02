"""size-set domain pack: the measurement report model and the policy's truth, with a switch per rule.

A report is built as data first (the spec, the garments measured, what each template prints), the features
bend it, and `truth(off=...)` answers as the policy says, or as an agent would that ignored the rules in `off`.
Every length is an exact Fraction in the house unit; the truth never reads a rendered page.
"""
from __future__ import annotations

import copy
import datetime as dt
import unicodedata
from fractions import Fraction as F

LETTER = (612.0, 792.0)
A4 = (595.0, 842.0)
A4_LANDSCAPE = (842.0, 595.0)
SCAN_ROUTES = {"scan_ocr", "scan_wrong_ocr", "scan_no_ocr", "scan_rotated"}
FORM_ROUTES = {"form", "form_mismatch"}

PREC = {"1/8": F(1, 8), "1/16": F(1, 16), "0.1": F(1, 10), "0.5": F(1, 2)}
CM_PER_IN = F(254, 100)


def norm(s):
    return "".join(unicodedata.normalize("NFKC", s).casefold().split())


# ------------------------------------------------------------------ numbers

def round_to(x: F, prec: F) -> F:
    """Nearest multiple of prec, halves up (policy 6)."""
    return (x / prec + F(1, 2)).__floor__() * prec


def convert(x: F, unit_from: str, unit_to: str) -> F:
    if unit_from == unit_to:
        return x
    return x * CM_PER_IN if unit_from == "in" else x / CM_PER_IN


def parse_qty(s: str) -> F:
    """`20 1/4`, `20-1/4`, `-1 1/8`, `+3/8`, `20.25`, `51.4` to a Fraction; vulgar fraction glyphs too."""
    for frac, g in GLYPHS.items():
        s = s.replace(g, f" {frac.numerator}/{frac.denominator}")
    s = unicodedata.normalize("NFKC", s).strip().replace("⁄", "/")
    sign = 1
    if s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s = s[1:].strip()
    s = s.replace("-", " ")
    total = F(0)
    for part in s.split():
        total += F(part)
    return sign * total


def fmt_qty(x: F, unit: str, signed: bool = False, notation: str = "frac", places: int | None = None) -> str:
    """A length in `unit`: inches as a mixed fraction in lowest terms (`20 1/4`), centimetres as a decimal.
    notation for inches: frac, dash (`20-1/4`), glyph (`20¼`), decimal (`20.25`)."""
    if x == 0:
        return "0" if signed else ("0" if unit == "in" and notation != "decimal" else "0.0")
    sign = "-" if x < 0 else ("+" if signed else "")
    x = abs(x)
    if unit == "cm" or notation == "decimal":
        p = places if places is not None else (max(1, _places_needed(x)) if unit == "cm" else _decimal_places(x))
        return f"{sign}{float(x):.{p}f}"
    whole, frac = divmod(x, 1)
    whole = int(whole)
    if frac == 0:
        return f"{sign}{whole}"
    if notation == "glyph" and frac in GLYPHS:
        return f"{sign}{whole if whole else ''}{GLYPHS[frac]}"
    sep = "-" if notation == "dash" else " "
    return f"{sign}{whole}{sep}{frac.numerator}/{frac.denominator}" if whole else f"{sign}{frac.numerator}/{frac.denominator}"


def _places_needed(x: F) -> int:
    """Decimal places that write x exactly (at most 4)."""
    for p in range(0, 5):
        if (x * 10 ** p).denominator == 1:
            return p
    return 4


def _decimal_places(x: F) -> int:
    for p in range(0, 5):
        if (x * 10 ** p).denominator == 1:
            return max(p, 2) if p else 0
    return 4


GLYPHS = {F(1, 4): "¼", F(1, 2): "½", F(3, 4): "¾", F(1, 8): "⅛", F(3, 8): "⅜", F(5, 8): "⅝", F(7, 8): "⅞"}


# ------------------------------------------------------------------ catalogue

# code, names (the first is the spec's own), half, critical, base value in inches at the base size,
# grade step in inches (regular sizes, above XL), tolerance in inches
TOP_POINTS = [
    ("101", ["Body length from HPS", "Front length from HPS", "Length HPS to hem"], False, True, F(28), (F(1), F(1)), F(1, 2)),
    ("102", ["Chest 1\" below armhole", "Chest width 1\" below AH", "1/2 Chest"], True, True, F(20), (F(1), F(3, 2)), F(1, 4)),
    ("103", ["Across shoulder", "Shoulder to shoulder", "Shoulder width seam to seam"], False, False, F(18), (F(1, 2), F(3, 4)), F(1, 4)),
    ("104", ["Sleeve length from CB", "CB sleeve length", "Sleeve length from centre back neck"], False, True, F(34), (F(1, 2), F(3, 4)), F(1, 2)),
    ("105", ["Armhole straight", "Armhole depth (straight)", "AH straight"], False, False, F(10), (F(1, 2), F(1, 2)), F(1, 4)),
    ("106", ["Bicep 1\" below armhole", "1/2 Bicep", "Upper arm width 1\" below AH"], True, False, F(15, 2), (F(3, 8), F(1, 2)), F(1, 4)),
    ("107", ["Cuff opening", "1/2 Sleeve opening", "Sleeve hem width"], True, False, F(4), (F(1, 8), F(1, 8)), F(1, 8)),
    ("108", ["Hem width", "1/2 Bottom opening", "Bottom width at hem"], True, False, F(20), (F(1), F(3, 2)), F(1, 4)),
    ("109", ["Neck width", "Neck opening seam to seam", "Neck width seam to seam"], False, False, F(7), (F(1, 4), F(1, 4)), F(1, 8)),
    ("110", ["Front neck drop", "Front drop from HPS", "Neck drop front from HPS"], False, False, F(7, 2), (F(1, 8), F(1, 8)), F(1, 8)),
]
BOTTOM_POINTS = [
    ("201", ["Waist relaxed", "1/2 Waist (relaxed)", "Waist width relaxed"], True, True, F(16), (F(1), F(1)), F(1, 4)),
    ("202", ["Hip 8\" below waist", "1/2 Hip at 8\" from waist", "Hip width 8\" below waistband"], True, False, F(21), (F(1), F(3, 2)), F(1, 4)),
    ("203", ["Front rise", "Front rise incl. waistband", "Rise front to top of waistband"], False, False, F(11), (F(1, 4), F(3, 8)), F(1, 4)),
    ("204", ["Back rise", "Back rise incl. waistband", "Rise back to top of waistband"], False, False, F(15), (F(1, 4), F(3, 8)), F(1, 4)),
    ("205", ["Inseam", "Inside leg length", "Inseam length crotch to hem"], False, True, F(31), (F(0), F(0)), F(1, 2)),
    ("206", ["Thigh 1\" below crotch", "1/2 Thigh", "Thigh width 1\" below crotch"], True, False, F(12), (F(1, 2), F(3, 4)), F(1, 4)),
    ("207", ["Knee", "1/2 Knee at 13\" from crotch", "Knee width 13\" below crotch"], True, False, F(9), (F(3, 8), F(1, 2)), F(1, 4)),
    ("208", ["Leg opening", "1/2 Leg opening", "Hem width at leg opening"], True, False, F(7), (F(1, 4), F(1, 4)), F(1, 8)),
    ("209", ["Outseam", "Outside leg length", "Side length incl. waistband"], False, True, F(42), (F(1, 2), F(1, 2)), F(1, 2)),
]
GARMENTS = [
    # name, style code prefix, points, overrides of base values (inches), size range key
    ("Men's training tee", "TEE", TOP_POINTS, {}, "alpha"),
    ("Pullover hoodie", "HOOD", TOP_POINTS, {"101": F(27), "102": F(22), "106": F(17, 2), "107": F(9, 2)}, "alpha"),
    ("Track jacket", "TRK", TOP_POINTS, {"101": F(26), "102": F(21), "104": F(35), "109": F(15, 2)}, "alpha"),
    ("Women's running short", "SHRT", BOTTOM_POINTS, {"205": F(4), "209": F(14), "201": F(14), "202": F(19)}, "women"),
    ("Woven training pant", "PANT", BOTTOM_POINTS, {}, "waist"),
    ("Compression legging", "LEG", BOTTOM_POINTS, {"201": F(13), "202": F(17), "206": F(10), "207": F(15, 2), "208": F(9, 2)}, "women"),
]
EXTRA_POINTS = [("115", "Pocket opening"), ("116", "Collar height at CB"), ("117", "Label placement from HPS"),
                ("215", "Waistband height"), ("216", "Pocket bag length"), ("217", "Fly length")]
SIZE_RANGES = {"alpha": (["XS", "S", "M", "L", "XL", "XXL"], "M"), "women": (["XS", "S", "M", "L", "XL"], "M"),
               "waist": (["28", "30", "32", "34", "36", "38"], "32")}
TOL_CM = {F(1, 8): F(1, 2), F(1, 4): F(1, 2), F(1, 2): F(1)}

HOUSES = {
    "yongsheng": dict(
        name="Yongsheng Garment Co., Ltd.", address="No. 6 Jinxiu Road, Humen, Dongguan 523900, China",
        font="Carlito", size=A4_LANDSCAPE, date_style="iso", title="SIZE SET MEASUREMENT CHART",
        layout="subcols", prints=("spec", "diff"), piece_word="Pc {n}",
        remeasure_word="Re-measured after pressing on {date}",
        meta={"Creator": "Microsoft Excel", "Producer": "Microsoft: Print To PDF"}),
    "plm": dict(
        name="Northline Athletic, Technical Design", address="Measurement form MF-21, exported from PLM",
        font="Roboto", size=LETTER, date_style="mdy", title="Sample Measurement Form",
        layout="columns", prints=("tol",), piece_word="{size} ({n})",
        remeasure_word="Re-measurement {date}",
        meta={"Producer": "ReportLab PDF Library - www.reportlab.com", "Creator": "PLM Export Service 4.2"}),
    "inspect": dict(
        name="Meridian Inspection Services Ltd.", address="Unit 7, 2/F, Kwai Fong Industrial Centre, Hong Kong",
        font="DejaVuSerif", size=A4, date_style="dmy", title="Measurement Inspection Report",
        layout="blocks", prints=("result",), piece_word="Sample {letter}",
        remeasure_word="Second measurement, {date}, after steaming",
        meta={"Creator": "PScript5.dll Version 5.2.2", "Title": "Microsoft Word - Inspection Report"}),
    "tablet": dict(
        name="QC Measure 3.1", address="Export from the vendor's QC tablet",
        font="Liberation", size=LETTER, date_style="iso", title="Measurement session",
        layout="pages", prints=("spec", "deviation", "status"), piece_word="garment #{n}",
        remeasure_word="Re-measured {date}",
        meta={"Producer": "Skia/PDF m118", "Creator": "QC Measure 3.1 (Android)"}),
}


def fmt_date(d: dt.date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "dmy":
        return d.strftime("%d %b %Y")
    return d.strftime("%B %d, %Y")


# ------------------------------------------------------------------ the policy

def spec_in_force(spec: dict, measured_on: dt.date, off=frozenset()) -> dict[tuple[str, str], F]:
    """(code, size) -> value in the house unit (policy 4)."""
    out = {}
    sizes = spec["sizes"]
    for p in spec["points"]:
        if "values" in p:
            vals = {s: parse_qty(p["values"][s]) for s in sizes}
            if 4 in off:
                vals = {s: parse_qty(p["values"][spec["base_size"]]) for s in sizes}
        else:
            base = parse_qty(p["base"])
            if 4 in off:
                vals = {s: base for s in sizes}
            else:
                vals = {}
                bi = sizes.index(spec["base_size"])
                v = base
                vals[sizes[bi]] = v
                for i in range(bi + 1, len(sizes)):
                    v = v + parse_qty(p["grade"][sizes[i]])
                    vals[sizes[i]] = v
                v = base
                for i in range(bi - 1, -1, -1):
                    v = v - parse_qty(p["grade"][sizes[i + 1]])
                    vals[sizes[i]] = v
        for s in sizes:
            out[(p["code"], s)] = vals[s]
    if 4 not in off:
        for r in sorted(spec["revisions"], key=lambda r: r["rev"]):
            if dt.date.fromisoformat(r["date"]) > measured_on:
                continue
            for s in (sizes if r["sizes"] == "all" else r["sizes"]):
                if "set" in r:
                    out[(r["code"], s)] = parse_qty(r["set"])
                else:
                    out[(r["code"], s)] += parse_qty(r["change"])
    return out


def decide(rows: list[dict], spec: dict, sizes_measured: set[str], off=frozenset()) -> str:
    """Policy 10 on the output rows."""
    crit = {p["code"] for p in spec["points"] if p["critical"]}
    by_piece: dict[tuple[str, int], list[dict]] = {}
    for r in rows:
        by_piece.setdefault((r["size"], r["piece"]), []).append(r)
    for (size, piece), rs in by_piece.items():
        out = [r for r in rs if r["within"] is False]
        if (10 not in off and any(r["code"] in crit for r in out)) or len(out) > 2:
            return "rejected"
    missing_size = any(s not in sizes_measured for s in spec["sizes"])
    if missing_size or any(r["within"] is None for r in rows):
        return "incomplete"
    if any(r["within"] is False for r in rows):
        return "approved_with_comments"
    return "approved"


# ------------------------------------------------------------------ the report

class Report:
    """Everything the report prints, the brand's spec, and the truth derived from both."""

    def __init__(self, rid, house, rnd, n_sizes, features, route):
        self.id, self.house_key, self.house = rid, house, HOUSES[house]
        self.rnd, self.features, self.route = rnd, set(features), route
        f = self.features
        g = rnd.choice(GARMENTS)
        self.garment, prefix, points, overrides, range_key = g
        self.style = f"{rnd.choice(['SS27', 'FW26', 'SP27'])}-{rnd.choice('MWU')}-{prefix}-{rnd.randint(101, 499):03d}"
        self.stage = rnd.choice(["size set", "pre-production sample", "fit sample"])
        inch_page = bool(f & {"fraction_dash", "fraction_glyph", "decimal_inches"})
        self.unit = "in" if "cm_report" in f or (inch_page and "in_report" not in f) else "cm" if "in_report" in f \
            else rnd.choice(["in", "in", "cm"])
        self.precision = rnd.choice(["1/8", "1/16"]) if self.unit == "in" else rnd.choice(["0.5", "0.1"])
        if "fraction_glyph" in f and self.unit == "in":
            self.precision = "1/8"                  # glyphs exist for eighths only
        if "fine_print" in f:                       # the page prints finer than the house keeps
            self.precision = "1/8" if self.unit == "in" else "0.5"
        self.prec = PREC[self.precision]
        full, base = SIZE_RANGES[range_key]
        bi = full.index(base)
        lo = max(0, min(bi, bi - rnd.randint(0, n_sizes - 1), len(full) - n_sizes))
        self.sizes = full[lo:lo + n_sizes]
        self.base_size = base
        self.measured_on = dt.date(2026, rnd.randint(8, 10), rnd.randint(1, 28))
        self.spec_points = []
        chosen = points if len(points) <= 9 else rnd.sample(points, rnd.randint(8, 10))
        for code, names, half, critical, base_in, (step, step_hi), tol_in in points:
            if code not in {c[0] for c in chosen}:
                continue
            base_v = overrides.get(code, base_in)
            if self.unit == "cm":
                base_v = round_to(base_v * CM_PER_IN, self.prec)
                step = round_to(step * CM_PER_IN, F(1, 2)) if step else F(0)
                step_hi = round_to(step_hi * CM_PER_IN, F(1, 2)) if step_hi else F(0)
                tol = TOL_CM[tol_in]
            else:
                tol = tol_in
            grade = {}
            for i, s in enumerate(full):
                if i == 0:
                    continue
                grade[s] = step_hi if full[i - 1] in ("XL", "36") or s in ("XXL", "38") else step
            self.spec_points.append({"code": code, "names": list(names), "half": half, "critical": critical,
                                     "base": base_v, "grade": grade, "tol_plus": tol, "tol_minus": tol})
        self.revisions: list[dict] = []
        self.graded = "graded" in f
        # what the report measures
        self.sizes_measured = list(self.sizes)
        self.pieces = {s: 1 for s in self.sizes}
        self.printed_unit = "cm" if "cm_report" in f else "in" if "in_report" in f else self.unit
        self.notation = "dash" if "fraction_dash" in f else "glyph" if "fraction_glyph" in f else \
            "decimal" if "decimal_inches" in f else "frac"
        if self.printed_unit != self.unit:
            self.printed_prec = F(1, 10) if self.printed_unit == "cm" else (F(1, 8) if "fraction_glyph" in f else F(1, 16))
        elif "fine_print" in f:
            self.printed_prec = F(1, 16) if self.unit == "in" else F(1, 10)
        else:
            self.printed_prec = self.prec
        if self.notation == "decimal" and self.printed_unit == "in":
            self.printed_prec = F(1, 100)              # two decimals, finer than any house precision
        self.full_circ: set[str] = set()
        self.by_name = "pom_by_name" in f
        self.long_names = "wrap_name" in f
        self.extra: list[tuple[str, str, dict]] = []     # (code, name, {(size, piece): printed value})
        # the true measurements in the house unit at the house precision, and what the page prints for each
        self.true: dict[tuple[str, str, int], F] = {}
        for p in self.spec_points:
            for s in self.sizes:
                for k in range(1, self.pieces[s] + 1):
                    self.true[(p["code"], s, k)] = None    # filled after the spec is final
        self.printed: dict[tuple[str, str, int], F | None] = {}
        self.remeasurements: list[dict] = []             # {"date", "kind", "unit", "values": {key: printed}}
        self.corrections: dict[tuple[str, str, int], dict] = {}   # key -> {"kind": "stamp"|"annot", "wrong": F}
        self.column_lies: dict = {"spec": {}, "diff": {}, "status": {}}
        self.late_revision = None

    # spec ------------------------------------------------------------
    def _values(self, p):
        """The base and grade of a point as per-size values, in the house unit."""
        spec = {"sizes": self.sizes, "base_size": self.base_size, "revisions": [],
                "points": [{"code": p["code"], "base": fmt_qty(p["base"], self.unit),
                            "grade": {s: fmt_qty(p["grade"][s], self.unit) for s in self.sizes[1:]}}]}
        return spec_in_force(spec, self.measured_on)

    @property
    def spec(self) -> dict:
        pts = []
        for p in self.spec_points:
            entry = {"code": p["code"], "names": p["names"], "half": p["half"], "critical": p["critical"],
                     "tol_plus": fmt_qty(p["tol_plus"], self.unit), "tol_minus": fmt_qty(p["tol_minus"], self.unit)}
            if self.graded:
                entry["base"] = fmt_qty(p["base"], self.unit)
                entry["grade"] = {s: fmt_qty(p["grade"][s], self.unit, signed=True) for s in self.sizes[1:]}
            else:
                vals = self._values(p)
                entry["values"] = {s: fmt_qty(vals[(p["code"], s)], self.unit) for s in self.sizes}
            pts.append(entry)
        revs = []
        for r in sorted(self.revisions, key=lambda r: r["rev"]):
            e = {"rev": r["rev"], "date": r["date"].isoformat(), "code": r["code"], "sizes": r["sizes"]}
            if "set" in r:
                e["set"] = fmt_qty(r["set"], self.unit)
            else:
                e["change"] = fmt_qty(r["change"], self.unit, signed=True)
            revs.append(e)
        return {"style": self.style, "stage": self.stage, "unit": self.unit, "precision": self.precision,
                "sizes": list(self.sizes), "base_size": self.base_size, "points": pts, "revisions": revs}

    def in_force(self, off=frozenset()):
        return spec_in_force(self.spec, self.measured_on, off)

    def point(self, code):
        return next(p for p in self.spec_points if p["code"] == code)

    # printing --------------------------------------------------------
    def print_value(self, key, value_house: F) -> F:
        """What the page prints for a true measurement: in the printed unit, at the printed precision, doubled
        for a full-circumference point."""
        v = value_house
        if key[0] in self.full_circ:
            v = v * 2
        v = convert(v, self.unit, self.printed_unit)
        return round_to(v, self.printed_prec)

    def house_value(self, key, printed: F, unit: str, off=frozenset()) -> F:
        """Policy 5 and 6 on a printed value."""
        v = printed if 5 in off else convert(printed, unit, self.unit)
        if 6 in off:
            return v
        if key[0] in self.full_circ:
            v = v / 2
        return round_to(v, self.prec)

    # truth -----------------------------------------------------------
    def truth(self, off=frozenset()) -> dict:
        force = self.in_force(off)
        rows = []
        for p in self.spec_points:
            for s in self.sizes:
                n = self.pieces.get(s, 1) if s in self.sizes_measured else 1
                for k in range(1, n + 1):
                    key = (p["code"], s, k)
                    printed, unit = self._final_print(key, off)
                    spec_v = force[(p["code"], s)]
                    row = {"code": p["code"], "size": s, "piece": k, "measured": None,
                           "spec": fmt_qty(spec_v, self.unit), "deviation": None, "within": None}
                    if printed is not None:
                        m = self.house_value(key, printed, unit, off)
                        d = m - spec_v
                        hi, lo = p["tol_plus"], (p["tol_plus"] if 8 in off else p["tol_minus"])
                        within = spec_v - lo <= m <= spec_v + hi
                        if 3 in off:
                            if key in self.column_lies["status"]:
                                within = self.column_lies["status"][key]
                            if key in self.column_lies["diff"]:
                                d = self.column_lies["diff"][key]
                        row.update({"measured": fmt_qty(m, self.unit), "deviation": fmt_qty(d, self.unit, signed=True),
                                    "within": within})
                    elif 7 in off:
                        continue
                    rows.append(row)
        measured = set(self.sizes_measured)
        if 7 in off:
            measured = set(self.sizes)
        return {"style": self.style, "measured_on": self.measured_on.isoformat(), "measurements": rows,
                "decision": decide(rows, self.spec, measured, off)}

    def _final_print(self, key, off=frozenset()):
        """The printed value that stands for `key` after corrections and re-measurements, with its unit."""
        if key[1] not in self.sizes_measured or key not in self.printed:
            return None, None
        best = (self.measured_on, 0, self.printed[key], self.printed_unit)
        if key in self.corrections:
            best = (self.measured_on, 0, self.corrections[key]["right"], self.printed_unit)
        if 9 not in off:
            for i, r in enumerate(self.remeasurements, 1):
                if key in r["values"] and (r["date"], i) > best[:2]:
                    best = (r["date"], i, r["values"][key], r["unit"])
        return best[2], best[3]


# ------------------------------------------------------------------ features

def _draw_true(c: Report):
    """Measurements within tolerance for every point, size and piece, at the house precision."""
    rnd, force = c.rnd, c.in_force()
    for key in list(c.true):
        p = c.point(key[0])
        steps = int(p["tol_minus"] / c.prec), int(p["tol_plus"] / c.prec)
        d = rnd.choice(list(range(-steps[0], steps[1] + 1)) + [0, 0, 0])
        c.true[key] = force[(key[0], key[1])] + d * c.prec


def apply_features(c: Report):
    rnd, f = c.rnd, c.features
    sizes = c.sizes
    noncrit = [p for p in c.spec_points if not p["critical"]]
    crit = [p for p in c.spec_points if p["critical"]]
    before = lambda days: c.measured_on - dt.timedelta(days=days)

    # rule 4: revisions and grading
    if "rev_set" in f:
        p = rnd.choice(c.spec_points)
        vals = c._values(p)
        s_from = rnd.randint(0, len(sizes) - 1)
        tgt = sizes[s_from:]
        c.revisions.append({"rev": 2, "date": before(rnd.randint(20, 60)), "code": p["code"], "sizes": tgt,
                            "set": vals[(p["code"], tgt[0])] + rnd.choice([-2, -1, 1, 2]) * p["tol_plus"]})
    if "rev_change" in f:
        p = rnd.choice([q for q in c.spec_points if not any(r["code"] == q["code"] for r in c.revisions)])
        c.revisions.append({"rev": len(c.revisions) + 2, "date": before(rnd.randint(10, 50)), "code": p["code"],
                            "sizes": "all", "change": rnd.choice([-2, -1, 1, 2]) * p["tol_plus"]})
    if "rev_twice" in f:
        p = rnd.choice(c.spec_points)
        vals = c._values(p)
        n = len(c.revisions)
        c.revisions.append({"rev": n + 2, "date": before(rnd.randint(40, 70)), "code": p["code"], "sizes": "all",
                            "change": 2 * p["tol_plus"]})
        c.revisions.append({"rev": n + 3, "date": before(rnd.randint(5, 30)), "code": p["code"],
                            "sizes": [sizes[0]], "set": vals[(p["code"], sizes[0])] - 2 * p["tol_plus"]})
    if "rev_late" in f:
        p = rnd.choice(c.spec_points)
        c.revisions.append({"rev": len(c.revisions) + 2, "date": c.measured_on + dt.timedelta(days=rnd.randint(3, 30)),
                            "code": p["code"], "sizes": "all", "change": 3 * p["tol_plus"]})
        c.late_revision = c.revisions[-1]
    # rule 7: sizes, pieces, points
    if "size_order" in f and len(sizes) > 1:
        order = list(sizes)
        while order == list(sizes):
            rnd.shuffle(order)
        c.sizes_measured = order
    if "size_missing" in f and len(sizes) > 1:
        gone = rnd.choice([s for s in sizes if s != c.base_size] or sizes)
        c.sizes_measured = [s for s in c.sizes_measured if s != gone]
    if "two_pieces" in f:
        for s in rnd.sample(c.sizes_measured, k=max(1, len(c.sizes_measured) // 2)):
            c.pieces[s] = 2
    c.true = {}
    for p in c.spec_points:
        for s in c.sizes_measured:
            for k in range(1, c.pieces[s] + 1):
                c.true[(p["code"], s, k)] = None
    _draw_true(c)
    force = c.in_force()
    keys = list(c.true)
    used: set = set()

    def pick(pool):
        k = rnd.choice([k for k in pool if k not in used])
        used.add(k)
        return k

    # rule 8: tolerance
    if "asym_tol" in f:
        p = rnd.choice(noncrit)
        p["tol_plus"], p["tol_minus"] = p["tol_plus"] * 2, p["tol_minus"]
        key = pick([k for k in keys if k[0] == p["code"]])
        c.true[key] = force[key[:2]] - p["tol_minus"] - c.prec   # out below, within above
    if "tol_edge" in f:
        p = rnd.choice(c.spec_points)
        key = pick([k for k in keys if k[0] == p["code"]])
        c.true[key] = force[key[:2]] + p["tol_plus"]
    # rule 10: decisions
    if "critical_out" in f:
        p = rnd.choice(crit)
        key = pick([k for k in keys if k[0] == p["code"]])
        c.true[key] = force[key[:2]] + rnd.choice([-1, 1]) * (p["tol_plus"] + rnd.randint(1, 3) * c.prec)
    if "many_out" in f:
        s = rnd.choice(c.sizes_measured)
        for p in rnd.sample(noncrit, 3):
            key = (p["code"], s, 1)
            used.add(key)
            c.true[key] = force[key[:2]] + rnd.choice([-1, 1]) * (p["tol_plus"] + rnd.randint(1, 2) * c.prec)
    if "comments_only" in f:
        for p in rnd.sample(noncrit, rnd.randint(1, 2)):
            key = pick([k for k in keys if k[0] == p["code"]])
            c.true[key] = force[key[:2]] + rnd.choice([-1, 1]) * (p["tol_plus"] + rnd.randint(1, 2) * c.prec)
    # what the page prints
    if "full_circ" in f:
        halves = [p["code"] for p in c.spec_points if p["half"]]
        c.full_circ = set(rnd.sample(halves, rnd.randint(1, min(2, len(halves)))))
    for key, v in c.true.items():
        c.printed[key] = c.print_value(key, v)
    # rule 6: rounding at the edge. round_edge prints just under the lower bound, which rounds up (halves up)
    # onto it: within. round_fail prints at or past the half step above the upper bound: rounds off it, out.
    for name, inside in (("round_edge", True), ("round_fail", False)):
        if name not in f:
            continue
        p = rnd.choice(noncrit)
        key = pick([k for k in keys if k[0] == p["code"]])
        lower, upper = force[key[:2]] - p["tol_minus"], force[key[:2]] + p["tol_plus"]
        lo_t, hi_t = (lower - c.prec / 2, lower) if inside else (upper + c.prec / 2, upper + c.prec)
        mult = 2 if key[0] in c.full_circ else 1
        start = (convert(lo_t * mult, c.unit, c.printed_unit) / c.printed_prec).__floor__() - 2
        stop = (convert(hi_t * mult, c.unit, c.printed_unit) / c.printed_prec).__floor__() + 3
        found = None
        for n in range(start, stop):
            v = n * c.printed_prec
            raw = convert(v, c.printed_unit, c.unit) / mult
            if lo_t <= raw < hi_t:
                found = v
                break
        if found is None:                                 # same unit and precision: no half step to print
            c.true[key] = lower if inside else upper + c.prec
            found = c.print_value(key, c.true[key])
        c.printed[key] = found
        c.true[key] = c.house_value(key, found, c.printed_unit)
    if "pom_missing" in f:
        key = pick(keys)
        c.printed[key] = None
    if "extra_pom" in f:
        pool = [e for e in EXTRA_POINTS if e[0][0] == c.spec_points[0]["code"][0]]
        code, name = rnd.choice(pool)
        base = F(rnd.randint(2, 6))
        c.extra.append((code, name, {(s, k): round_to(convert(base + rnd.randint(-2, 2) * F(1, 8), "in", c.printed_unit), c.printed_prec)
                                     for s in c.sizes_measured for k in range(1, c.pieces[s] + 1)}))
    # rule 2: corrections over a printed value
    for name in ("stamp_value", "annot_correction"):
        if name in f:
            free = [k for k in keys if c.printed.get(k) is not None and k not in used]
            key = pick(free or [k for k in keys if c.printed.get(k) is not None])
            right = c.printed[key]
            wrong = right + rnd.choice([-3, -2, 2, 3]) * c.printed_prec * (2 if c.printed_unit == "cm" else 1)
            c.corrections[key] = {"kind": "stamp" if name == "stamp_value" else "annot", "wrong": wrong, "right": right}
    # rule 9: re-measurements
    if f & {"remeasure_block", "remeasure_page", "remeasure_twice"}:
        kind = "page" if "remeasure_page" in f else "block"
        unit = ("cm" if c.printed_unit == "in" else "in") if "mixed_units" in f else c.printed_unit
        prec = c.printed_prec if unit == c.printed_unit else (F(1, 10) if unit == "cm" else F(1, 8))
        later = c.measured_on + dt.timedelta(days=rnd.randint(2, 9))
        if kind == "page":
            clean = [sz for sz in c.sizes_measured if not any(k[1] == sz for k in c.corrections)]
            s = rnd.choice(clean or c.sizes_measured)
            pool = [k for k in keys if k[1] == s and c.printed.get(k) is not None]
        else:
            pool = [k for k in keys if c.printed.get(k) is not None and k not in c.corrections]
        changed = rnd.sample([k for k in pool if k not in used], min(len(pool), rnd.randint(2, 4)))
        values = {}
        for k in (pool if kind == "page" else changed):
            p = c.point(k[0])
            if k in changed:
                used.add(k)
                c.true[k] = force[k[:2]] + rnd.choice([-1, 0, 1]) * p["tol_plus"]
            v = c.true[k] * (2 if k[0] in c.full_circ else 1)
            values[k] = round_to(convert(v, c.unit, unit), prec)
        c.remeasurements.append({"date": later, "kind": kind, "unit": unit, "values": values, "size": s if kind == "page" else None})
        if "remeasure_twice" in f:
            k = changed[0]
            p = c.point(k[0])
            c.true[k] = force[k[:2]] + rnd.choice([-1, 1]) * p["tol_plus"]
            v = c.true[k] * (2 if k[0] in c.full_circ else 1)
            c.remeasurements.append({"date": later + dt.timedelta(days=rnd.randint(1, 5)), "kind": "block",
                                     "unit": c.printed_unit, "values": {k: round_to(convert(v, c.unit, c.printed_unit), c.printed_prec)},
                                     "size": None})
    # rule 3: the report's own columns lie
    prints = c.house["prints"]
    if "spec_stale" in f:
        stale = spec_in_force(c.spec, c.measured_on - dt.timedelta(days=400))   # before every revision
        for (code, sz), v in stale.items():
            if v != force[(code, sz)]:
                c.column_lies["spec"][(code, sz)] = v
                for key in keys:
                    if key[:2] == (code, sz) and c.printed.get(key) is not None and "diff" in prints:
                        c.column_lies["diff"][key] = c.house_value(key, c.printed[key], c.printed_unit) - v
    if "diff_wrong" in f:
        for key in rnd.sample([k for k in keys if c.printed.get(k) is not None], 3):
            c.column_lies["diff"][key] = c.house_value(key, c.printed[key], c.printed_unit) - force[key[:2]] + rnd.choice([-1, 1]) * c.prec
    if "status_lies" in f:
        outs = [k for k in keys if c.printed.get(k) is not None and not
                (force[k[:2]] - c.point(k[0])["tol_minus"] <= c.house_value(k, c.printed[k], c.printed_unit)
                 <= force[k[:2]] + c.point(k[0])["tol_plus"])]
        if outs:
            for k in outs:
                c.column_lies["status"][k] = True       # marked as passing although out
        else:
            k = pick([k for k in keys if c.printed.get(k) is not None])
            c.column_lies["status"][k] = False      # marked as failing although within


def min_units(features: set[str]) -> int:
    return 2 if features & {"size_order", "size_missing"} else 1

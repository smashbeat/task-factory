"""The lot-release verifier's comparison: exact numbers, order-free findings, hyphen-free lots, fail closed."""
import importlib.util
import json
from pathlib import Path

PACK = Path(__file__).parent.parent / "packs" / "lot-release"
spec = importlib.util.spec_from_file_location("lot_compare", PACK / "task" / "tests" / "compare.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)

TRUTH = {
    "product": "Daily Mineral Complex", "lot": "SNL-260417", "manufactured_on": "2026-03-09", "expires_on": "2028-03-09",
    "yield": 5880, "ingredients": [
        {"code": "ING-01", "supplier": "Hengxin Nutrition Co., Ltd.", "lot": "L-00123", "dispensed": "12.500", "certificate": "ok"},
        {"code": "ING-02", "supplier": None, "lot": None, "dispensed": None, "certificate": "missing"},
    ],
    "label": {"lot": "SNL260417", "expiry": "2028-03-09"}, "finished": "ok", "packing": {"units": 5880},
    "findings": ["ingredient_missing:ING-02", "label_allergen"], "decision": "hold",
}


def _sub(**changes):
    s = json.loads(json.dumps(TRUTH))
    s.update(changes)
    return s


def test_the_truth_passes_and_numbers_compare_exactly():
    assert compare.compare(TRUTH, TRUTH) == []
    s = _sub()
    s["ingredients"][0]["dispensed"] = 12.5
    s["yield"] = "5880"
    s["packing"]["units"] = 5880.0
    assert compare.compare(s, TRUTH) == []


def test_findings_in_any_order_and_lots_without_hyphens():
    s = _sub(findings=["label_allergen", "ingredient_missing:ING-02"], lot="SNL260417")
    s["ingredients"][0]["lot"] = "L00123"
    s["label"]["lot"] = "snl-260417"
    assert compare.compare(s, TRUTH) == []
    s["ingredients"][0]["lot"] = "L123"
    assert any("lot" in d for d in compare.compare(s, TRUTH))


def test_differences_are_reported():
    s = _sub(decision="released", findings=[])
    diffs = compare.compare(s, TRUTH)
    assert any(d.startswith("decision") for d in diffs) and any(d.startswith("findings") for d in diffs)
    s = _sub()
    del s["packing"]
    s["ingredients"].append({"code": "ING-03", "supplier": None, "lot": None, "dispensed": None, "certificate": "missing"})
    diffs = compare.compare(s, TRUTH)
    assert any("top-level keys" in d for d in diffs) and any("rows reported" in d for d in diffs)
    assert compare.compare("not an object", TRUTH) == ["OUT.json is not an object"]

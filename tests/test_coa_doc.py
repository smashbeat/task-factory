"""The certificate library: the coa model lifted into the forge, with the keywords other packs need."""
import datetime as dt
import random

from taskfactory.forge import coa_doc


def _default(seed=7):
    c = coa_doc.Cert("c1", "hengxin", random.Random(seed), 1, {"fail"}, "digital")
    coa_doc.apply_features(c)
    return c


def test_default_call_draws_as_before():
    a, b = _default(), _default()
    assert a.truth() == b.truth()
    t = a.truth()["lots"][0]
    assert t["material"] == a.material[0] and t["supplier"] == "Hengxin Nutrition Co., Ltd."


def test_overrides_land_in_the_truth_without_moving_the_draws():
    plain = _default()
    c = coa_doc.Cert("c1", "hengxin", random.Random(7), 1, {"fail"}, "digital",
                     material=coa_doc.MATERIALS[3], lot_numbers=["L-240871"], received=dt.date(2026, 3, 9))
    coa_doc.apply_features(c)
    lot = c.truth()["lots"][0]
    assert lot["material"] == coa_doc.MATERIALS[3][0] and lot["lot_number"] == "L-240871"
    assert c.received == dt.date(2026, 3, 9) and c.spec["received"] == "2026-03-09"
    # the same tests were chosen and the same results drawn: the keywords override, they do not reseed
    assert [r["test"] for r in lot["results"]] == [r["test"] for r in plain.truth()["lots"][0]["results"]]
    assert [r["result"] for r in lot["results"]] == [r["result"] for r in plain.truth()["lots"][0]["results"]]


def test_a_house_dict_and_another_catalogue_work():
    lab = dict(coa_doc.HOUSES["bluewater"], key="lab", name="Sierra Nutraceutical Labs QC")
    finished = [t for t in coa_doc.TESTS if t[6] in ("metal", "micro")] + [coa_doc.TESTS[3]]  # metals, micro, LOD
    c = coa_doc.Cert("fp", lab, random.Random(3), 1, set(), "digital", catalogue=finished,
                     material=("Daily Zinc Complex Capsules", "Capsules"), lot_numbers=["240871"])
    coa_doc.apply_features(c)
    lot = c.truth()["lots"][0]
    assert c.house_key == "lab" and lot["supplier"] == "Sierra Nutraceutical Labs QC"
    assert {r["test"] for r in lot["results"]} <= {t[0] for t in finished}
    assert lot["material"] == "Daily Zinc Complex Capsules" and lot["lot_number"] == "240871"

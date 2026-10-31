from taskfactory.diffs import Diff, parse_diff


def test_lot_count():
    assert parse_diff("4 lots reported, certificate has 3") == Diff("lot_count", got=4, want=3)


def test_row_count():
    assert parse_diff("lot 0: 16 result rows, certificate prints 8") == Diff("row_count", lot=0, got=16, want=8)


def test_row_field():
    d = parse_diff("lot 0 row 4 result: '1.4' != '0.15'")
    assert d == Diff("field", lot=0, row=4, field="result", got="1.4", want="0.15")


def test_lot_field_with_none():
    d = parse_diff("lot 1 retest_date: None != '2027-10-31'")
    assert d == Diff("field", lot=1, field="retest_date", got=None, want="2027-10-31")


def test_unknown_line_is_kept():
    d = parse_diff("something the parser has never seen")
    assert d.kind == "other" and d.text == "something the parser has never seen"

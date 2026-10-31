"""One line of a verifier's diff, typed.

The coa-intake verifier reports up to fifteen differences per failed item, one per line. Three shapes carry
all of them: too many or too few lots, too many or too few rows in a lot, and a field whose value differs.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any

_LOT_COUNT = re.compile(r"^(\d+) lots reported, certificate has (\d+)$")
_ROW_COUNT = re.compile(r"^lot (\d+): (\d+) result rows, certificate prints (\d+)$")
_FIELD = re.compile(r"^lot (\d+)(?: row (\d+))? (\w+): (.+?) != (.+)$")


@dataclass(frozen=True)
class Diff:
    kind: str  # lot_count, row_count, field, other
    lot: int | None = None
    row: int | None = None
    field: str | None = None
    got: Any = None
    want: Any = None
    text: str = ""


def _value(s: str) -> Any:
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return s


def parse_diff(line: str) -> Diff:
    line = line.strip()
    if m := _LOT_COUNT.match(line):
        return Diff("lot_count", got=int(m[1]), want=int(m[2]))
    if m := _ROW_COUNT.match(line):
        return Diff("row_count", lot=int(m[1]), got=int(m[2]), want=int(m[3]))
    if m := _FIELD.match(line):
        row = int(m[2]) if m[2] is not None else None
        return Diff("field", lot=int(m[1]), row=row, field=m[3], got=_value(m[4]), want=_value(m[5]))
    return Diff("other", text=line)

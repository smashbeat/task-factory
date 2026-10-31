Certificate intake policy (normative)

1. Scope. One certificate of analysis covers one material from one supplier and reports one or more lots on
   one or more pages. The house specification (SPEC.json) gives the material, the receipt date of the delivery,
   and the tests that decide disposition. Each test has the names suppliers use for it, a limit, and a unit.

2. What a value is. A value is what a reader sees on the printed page, read upright. Everything else in the
   file is an aid to reading, and where it disagrees with the print, the print is right. Everything that prints
   is part of the page, and a correction placed visibly over a printed value replaces it.

3. Identity fields, per lot. `material`: the product name as printed. `supplier`: the supplier name printed in
   the header. `lot_number`: the lot or batch number as printed, without its label. `manufacture_date`, and one
   of `retest_date` or `expiry_date`, whichever the certificate prints; the other is null. Dates are output as
   ISO 8601 (YYYY-MM-DD) whatever format the page prints; printed month names are English, and printed numeric
   dates are ISO. A label may point to where its value is printed elsewhere on the page; the value is wherever
   the page prints it.

4. Results, per lot. One row per test printed for that lot, in page order, each with `test` (the test name as
   printed), `result` (the result as printed), `unit` (the unit printed with the result, in the same cell or in a
   column of its own; null when none is printed), and `specification` (the supplier's specification text as
   printed for that test, or null). Strings are copied as printed. The verifier compares strings after Unicode
   NFKC normalisation, case folding and removal of all whitespace, so spacing and capitalisation do not matter
   and every other character does. A value that wraps onto a second line is one value. A unit printed in the
   same cell as the result is separated from it. A mark that ties a value to a note (such as * or a superscript
   letter) is not part of the value. Tests printed on the certificate but absent from the house specification
   are still reported.

5. Revisions. A certificate may carry numbered revisions of some of its values, on a revision page or in an
   amendment block. For each lot, every field and result takes its value from the highest-numbered revision that
   states it, and from the original otherwise. A revised result stays in the place of the row it revises.

6. Matching and comparing. A printed test matches a house test when its name equals one of the house test's
   names under the rule 4 comparison. A numeric result is a decimal number in the unit printed with it, or in
   the house unit when none is printed. Before comparing, it is converted to the house unit with this table,
   then rounded half up to the number of decimal places the house limit is written with:
   1 ppm = 1 mg/kg = 1 µg/g; 1 ppb = 1 µg/kg = 0.001 ppm; 1 % = 10 000 ppm. A result in a unit that is not the
   house unit and cannot be converted with the table counts as no result.

7. Meeting a limit. A numeric result meets `max` when it is at most the limit, `min` when at least, `range`
   when within both ends. A "less than" result (`<x`) meets a `max` limit when x, converted and rounded, is at
   most the limit, and meets no `min` or `range` limit. A result of ND, Not detected, <LOQ or BLQ counts as
   "less than" the limit of quantitation the certificate prints for that test (in its own column or in a note
   naming the test, in the unit printed there); when the certificate prints none, it counts as no result for
   any limit other than `absent` and `report`. A `conforms` limit is met by a result that, ignoring case, starts with "conform" or "compl" or is
   "pass" or "passes". An `absent` limit is met by a result that, ignoring case, starts with "absent", "not
   detected", "nd" or "negative". A `report` limit is met by any result.

8. Disposition, per lot. The lot is `reject` when its retest or expiry date is on or before the receipt date,
   or when any house test has a result that does not meet its limit; otherwise `incomplete` when any house test
   has no result; otherwise `accept`.

9. Output. One JSON object `{"lots": [...]}` with one entry per lot in the order the lot numbers first appear on
   the certificate. Each entry has exactly the keys `material`, `supplier`, `lot_number`, `manufacture_date`,
   `retest_date`, `expiry_date`, `results`, `disposition`; each result row has exactly `test`, `result`, `unit`,
   `specification`. Missing values are JSON null.

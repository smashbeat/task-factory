# size-set: the garment measurement pack (design)

Third family for the factory, and the first chosen for commercial reach: every sportswear brand and every one of its vendors does this work on every style, every season. A brand's technical team sends the factory a tech pack with a graded measurement spec. The factory sews a size set (one piece per size) or a pre-production sample, measures each piece at every point of measure, and sends back a measurement report. Someone at the brand then checks each value against the spec in force, with its tolerance, and decides whether the sample is approved, approved with comments, or rejected. The reports arrive as PDFs produced every way a vendor produces them, in inches or centimetres, in the vendor's own template, against whatever revision of the spec the factory had on hand.

The task: build the intake tool that reads one measurement report and the brand's spec, and writes every measurement, its deviation and the decision exactly as the policy defines them. Same five mechanisms as coa-intake:

| Mechanism | Here |
|---|---|
| A cheap channel that lies | the PDF text layer and form fields (docforge routes), and the report's own printed spec, difference and pass/fail columns |
| The agent must build a reader | four vendor templates, grids with sub-columns, transposed blocks, landscape pages, fractions in three notations, scans |
| Stacking | 4 to 6 features per hidden report |
| Supersession | spec revisions dated against the measurement date; re-measurements after pressing or correction; stamps and corrections over values |
| Exactness | inches to centimetres and back, halves of circumferences, rounding to the house precision, inclusive asymmetric tolerances, from a truth engine that never reads the page |

The pack is "brand spec versus supplier report", the shape the coa pack proved, on the same PDF forge. No new medium, so the build is a pack, not a forge.

## Inputs and output

- `ID.pdf`: one measurement report for one style and one sample stage, covering 1 to 6 sizes with one or two pieces per size, on one or more pages.
- `ID.spec.json`: the brand's spec for the style. `style`, `stage`, `unit` (`in` or `cm`), `precision` (`1/8`, `1/16`, `0.1` or `0.5`), `sizes` in order, `base_size`, `points` (each with `code`, `names`, `half`, `critical`, `tol_plus`, `tol_minus`, and either `values` per size or `base` plus `grade` increments per size), and `revisions` (each with `rev`, `date`, `code`, `sizes` or `all`, and either `set` or `change`).
- Tool: `python3 /app/intake/intake.py IN.pdf SPEC.json OUT.json`.
- Output: `{"style", "measured_on", "measurements": [...], "decision"}`. One measurement per spec point, spec size and piece, in spec order (points, then sizes, then pieces): `code`, `size`, `piece`, `measured`, `spec`, `deviation`, `within`. `piece` is the ordinal of the garment within its size in the order the report presents them (1, 2), never the printed label; a size the report does not measure has one piece's rows, all null. Values are written in the house unit; the verifier compares `measured`, `spec` and `deviation` as exact numbers (a mixed fraction or a decimal, either is right), and the other fields as strings after NFKC normalisation, case folding and whitespace removal. The truth is exact: a value is an integer count of the house precision.

## Styles (vendor templates)

| Style | Who | Layout | Unit habit |
|---|---|---|---|
| yongsheng | a Chinese garment factory, spreadsheet printout | points as rows; per size the sub-columns Spec, Act, Diff; A4 landscape | the house unit, unless the item carries `cm_report`, when it prints centimetres and its Spec column is the factory's own conversion |
| plm | the brand's own PLM-exported measurement form | points as rows with code, name, Tol+, Tol-; sizes as columns with actuals only; Letter | the house unit, fractions |
| inspect | a third-party inspection company | one block per size, points as rows, pieces as columns; signatures and an INSPECTED stamp; A4 | decimals in the house unit |
| tablet | a QC app export | one page per size and piece; rows of spec, measured, deviation and a PASS or FAIL mark; Letter | the house unit; its spec, deviation and status columns lie only where a feature says so |

Each style has its own fonts, date style (ISO, day-month-year, month-day-year), producer metadata and wording for pieces (pc 1, sample A, garment #2) and for re-measurements.

## Routes (docforge, unchanged)

`digital`, `distilled`, `outlined`, `scan_ocr`, `scan_wrong_ocr`, `scan_no_ocr`, `scan_rotated`, `form`, `form_mismatch`. Reading routes: the outlined and scanned ones. Route rules: `form_mismatch`, `scan_wrong_ocr` and `scan_rotated` exercise rule 2. Overlays: stamp, watermark, white decoy, visible correction annotation.

## Rules (policy, numbered as in the pack)

1. Scope: one report, one style, one stage, one or more sizes, one or two pieces per size; what the spec file gives. The report's header prints the measurement date, once; that is `measured_on`, and the date every other rule means by "the measurement date". A re-measurement prints its own date, which never changes `measured_on`.
2. What a value is: the print, read upright; everything else in the file is an aid; a correction placed visibly over a value (a stamp, an annotation) replaces what that place prints. (Same text as coa.)
3. The report's own columns: a spec, difference, deviation or pass/fail mark printed on the report is an aid; the spec in force and this policy decide. Mutant: trust the printed status and difference.
4. The spec in force: a point's value for a size is the spec's `values` entry, or `base` plus the increments from the base size to that size; then every revision applied in order of revision number, up to and including the highest revision dated on or before the measurement date. A revision with `set` replaces the value for the sizes it names; one with `change` adds to it. Mutant: the base value for every size, no revision.
5. Units and notation: a value is in the unit the report prints for it (a column header, a note such as "all measurements in cm", or the value's own suffix), else in the house unit. Inches print as mixed fractions (`20 1/4`, `20-1/4`, `20¼`) or decimals; 1 in is 2.54 cm. Mutant: the printed number taken as if in the house unit.
6. Half measures and rounding: a point marked `half` in the spec is measured flat; when the report says it measured the full circumference, the printed value is halved. The value is then rounded to the nearest house precision, halves up. Mutant: no halving, no rounding.
7. Which point, size and piece: a printed point matches a spec point by its code when the report prints codes, else by name under the rule 11 comparison; sizes are matched by label whatever their order; a piece is one measured garment, numbered in the order the report presents the pieces of its size; a spec point with no value for a piece is reported with `measured`, `deviation` and `within` null; a printed point the spec lacks is not reported. Mutant: missing points are dropped from the output and from the decision.
8. Tolerance: within when `spec - tol_minus <= measured <= spec + tol_plus`, inclusive, after rules 5 and 6. Mutant: symmetric, `tol_plus` both ways.
9. Re-measurements: a report may re-measure some values after pressing, washing or correction, in a dated block or on a dated later page. Among the original (dated by the measurement date) and every re-measurement that states a value, the latest date wins. A correction over a value (rule 2) changes what that place prints and nothing else. Mutant: the original values.
10. Decision: `rejected` when a critical point is out on any piece or more than two points are out on one piece; else `incomplete` when a spec size was not measured or a spec point has no value on some piece; else `approved_with_comments` when any point is out; else `approved`. Mutant: critical points count like any other.
11. Output: key sets, ordering, number formats.

Mutants: 3 to 10. Rules 1, 2 and 11 have none, as in coa.

## Features (traps)

Rule 4: `rev_set`, `rev_change`, `rev_twice` (later wins), `rev_late` (dated after the measurement, must not apply), `graded` (base plus increments, uneven above XL). Rule 5: `cm_report`, `in_report`, `fraction_dash`, `fraction_glyph` (the ¼ ½ ¾ ⅛ glyphs, which break in a distilled text layer the way ≤ did), `decimal_inches`, `unit_note`, `mixed_units` (the re-measurement block in the other unit). Rule 6: `full_circ`, `round_edge` (lands on the tolerance after rounding), `round_fail` (just outside after rounding). Rule 7: `size_order`, `size_missing`, `two_pieces`, `extra_pom`, `pom_missing`, `pom_by_name`, `wrap_name`. Rule 8: `asym_tol`, `tol_edge`. Rule 9: `remeasure_block`, `remeasure_page`, `remeasure_twice`. Rule 2: `stamp_value`, `annot_correction` (a correction over an original value; the generator never puts a correction and a re-measurement on the same value). Rule 10: `critical_out`, `many_out`, `comments_only`. Rule 3: `status_lies`, `spec_stale` (the report's spec column is an older revision), `diff_wrong`. Rule 11: `continuation`, `a4_continuation`. Reading: `watermark`, `white_decoy`, `scramble`.

Thirty-six features; every mutant rule decides several hidden items, and the plan shows each feature in a worked sample. The unit a template prints is drawn per item from the features, never fixed by the template, so rule 5 is decided only where a feature puts it.

## Calls made after the builder check

A fresh reviewer read this document as the builder. Its four questions and what I decided:

1. **Which date gates the revisions.** The header's measurement date, printed once; re-measurement dates never move it. Costs if wrong: a brand that evaluates a re-measured sample against the spec current at re-measurement would read rule 4 differently. Kept simple on purpose; the policy says so in rule 1.
2. **Rows for an unmeasured size and the meaning of `piece`.** Every spec size gets rows; an unmeasured size gets one piece of nulls; `piece` is an ordinal in report order, not the printed label. Fixes the row set so the exact verifier is fair.
3. **Several carriers on one value.** Corrections (stamp, annotation) change the print under them and are undated; re-measurements (block, page) are dated and the latest wins; the generator never stacks both on one value. Rule 9 now says it.
4. **One rule for units and rounding, with a template that always converts.** Split into rules 5 and 6, and the printed unit is a feature, never a template habit, so attribution can tell "did not convert" from "did not halve or round".

## Garments and points of measure

Tops (tee, hoodie, track jacket): body length from HPS, chest 1" below armhole (half), across shoulder, sleeve length from CB, armhole straight, bicep (half), cuff opening (half), hem (half), neck width, front neck drop. Bottoms (short, pant, legging): waist relaxed (half), hip at a stated depth (half), front rise, back rise, inseam, thigh (half), knee (half), leg opening (half), outseam. Size ranges: alpha XS to XXL, numeric waist 28 to 38, women's alpha. Values are drawn in the house unit at the house precision; grading increments differ by garment and are larger above XL. Vendor and brand names are invented.

## Builder changes

- **Extract docforge.** The coa pack's `render.py` holds the domain-free forge (Pen, scan simulation, Ghostscript routes, OCR layers, forms, stamps, corrections, white decoys) next to the certificate drawing. Move the forge to `src/taskfactory/forge/docforge.py` and have both packs import it. Proof it changed nothing: re-render coa seed 4001's samples and compare bytes with the shipped build (reportlab's invariant mode makes the PDFs deterministic). This was already on the factory's list.
- **Numeric compare.** The pack's `compare.py` parses the three numeric fields as exact rationals, so a right value in another notation passes.
- Nothing else: pack.toml, plan, gates, fix loop, holdout and trials are reused as they are. Generator and reference images are the coa ones.

## Environments

- Agent and reference image: the coa task image as is (python3, pymupdf, pdfplumber, tesseract, poppler, ghostscript, numpy, opencv).
- Generator image: the coa generator image as is (fonts the task image lacks, ocrmypdf).

## Open risks

- Grids are more regular than certificates: a table extractor may carry an agent further than it did on coa. The counter is in the templates (sub-columns, transposed blocks, landscape, wrapped names) and in the numeric traps that no extractor settles.
- A spec with revisions in JSON moves part of the difficulty out of the page. Rule 4 must stay in the page through the measurement date, which decides which revisions apply.
- Fraction glyphs and the full-circumference wording are the kind of trap a worked sample must show, or the fairness gate will flag them.

## Pilot log

- 2026-11-02, build. docforge extracted from the coa renderer into `src/taskfactory/forge/docforge.py` (36 of 41 coa items re-render identical in pixels, text, annotations and fields; the other 5 differ only by the scan noise draw, as run to run). Pack written: 11 rules, 41 features (the design said 36; `fine_print`, `size_order`, `two_pieces`, `extra_pom` and `wrap_name` were split out of broader ones). The planner silently dropped two thirds of the hidden slots because its rule-use penalty pushed every candidate under a fixed score floor; it now takes the best candidate whatever its score.
- Seed 1: 13 samples, 30 hidden; every feature in a sample, every route and style in the hidden set, every mutant rule deciding 2 to 7 hidden items.
- Model fixes found by the reference: a centimetre spec drew an eighth-inch precision when `fraction_glyph` was on; centimetre strings lost a decimal. The `fraction_glyph` trap is limited to the digital and distilled routes, where the text layer carries or loses the glyph; OCR of the glyph on a scan was no reading challenge an expert could meet fairly.
- Reference: the coa page reader (OCR plus text-layer arbitration) unchanged, plus a table walker. What it took to read every report: tokens land on the nearest header label at or right of their left edge (values print left-aligned under centred labels, which breaks any midpoint rule on wide columns); one-letter size labels OCR drops are read back from the ink between labels; a size repeated on a header line is its next piece; glued mixed fractions (`243/16`) split against the spec value; a stamped correction is read inset from its frame and replaces the words under it; a cell that reads empty or implausibly far from the spec is read again, first as a word of the whole row strip, then alone with rule lines and the neighbouring row's edge whitened. Renderer fix found the same way: an annotation box clipped its text.
- Result: 43 of 43 on seed 1 (build `out/build-set-1c`), slowest item 33 s against the 120 s limit; task assembled at `out/build-set-1c/task/size-set-s1` (18 MB).
- Holdout seed 1001 (`out/build-set-1001`): 40 of 43 on the first run, the three misses all reading slips (a row of values taken for a header because numeric sizes look like values; `7/18` for `7/8`; size labels OCR split over two lines above the Act header; a block's own unit line confused with a page header's). Fixed without any seed-specific code; 43 of 43 on both seeds, slowest 42 s.
- First Harbor pass: the oracle scored 0 because the verifier killed the reference at 120 s on its two CPUs while the holdout build and the agent shared the machine; the cause was a cell check that re-thresholded the whole 400 dpi page for every cell. Fixed. The Sonnet screen in that pass was void: the agent hit the account's five-hour usage limit after six minutes.
- Second pass: oracle 1, nop 0. **Sonnet 5.5 at the 2 h cap failed: 25 of 30**, killed at the timeout with a 9,051-line tool on disk (about $15, 476k output tokens). The five misses, each checked against the item's features: h02 took the re-measurement block's inch values as centimetres (`mixed_units`, rule 5); h05 lost the second pieces and a page of size groups (`two_pieces`, 54 rows for 81, rule 7); h04 left two of the reordered sizes null (`size_order`, `size_missing`, rule 7); h24 (outlined page) and h28 (sideways scan of a landscape page) came back all null, which are reading misses on routes the worked samples show. Three rule-decided failures and two reading failures: a fair fail by the attribution gate's own test. This is the first cheap screen a factory pilot has failed since coa-intake.
- Seed replay of Sonnet's finished program (gate 6; the artifact needs its redacted digit 1 restored first): seed 1 reproduces the verifier exactly, 38 of 43 with all 13 samples right and the same five hidden misses; fresh seed 1001 also 38 of 43, with three of its thirteen samples wrong (`mixed_units`, `fraction_glyph` with `wrap_name`, `scramble` with `diff_wrong`). The miss rate holds on a seed the agent never saw, so the failure is the program's reach, not one seed's luck.

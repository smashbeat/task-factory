# coa-intake-s4001: trials and attribution

Build 1k of the coa pack (seed 4001, difficulty knob on: 4 to 6 features per hidden certificate, 70% with several lots, 60% on reading routes). Oracle 1, nop 0. Task at `out/harbor-4/coa-intake-s4001`, jobs in `out/harbor-4/jobs`.

## Frontier trials

Bar: both model families fail 3 of 3. Met.

| Trial | Model | Score | Time | Ended |
|---|---|---|---|---|
| tf4-codex-1 | GPT-6.1 Sol, xhigh | 19 of 30 | 52 min | normally |
| tf4-codex-2 | GPT-6.1 Sol, xhigh | 11 of 30 | 38 min | normally |
| tf4-codex-3 | GPT-6.1 Sol, xhigh | 20 of 30 | 44 min | normally |
| tf4-opus-1 | Opus 5.5, max | 27 of 30 | 5 h | normally |
| tf4-opus-2 | Opus 5.5, max | 27 of 30 | 6 h 45 min | normally |
| tf4-opus-3 | Opus 5.5, max | 25 of 30 | 2 h 9 min | normally |

Misses:

- codex-2: h01 h04 h05 h06 h08 h09 h10 h11 h15 h16 h17 h19 h21 h23 h25 h26 h27 h28 h29
- codex-3: h02 h08 h09 h10 h11 h18 h19 h26 h27 h29
- opus-1: h05 h09 h29
- opus-2: h09 h23 h24
- opus-3: h05 h06 h09 h23 h29

## Attribution of the Opus misses (each checked on the rendered page)

| Item | Route and features | What the agent wrote | Class | Rule |
|---|---|---|---|---|
| h09 | distilled; missing, nd_loq_note, rev_page, rev_result, scramble, wrap | `s 1.0 ppm`, `a 1.0 ppm` or `�` for `≤ 1.0 ppm` | misreading: the `≤` is broken in the distilled text layer and visible on the page | 2 |
| h29 | distilled; alias, fail, round_fail, round_metal, scramble, wrap | same as h09 | misreading, same trap | 2 |
| h05 | scan_wrong_ocr, 2 lots; alias, nd_loq_note, round_fail, round_min, stamp_retest, units_bad | retest date null, or "see stamp" | written rule missed: the retest date is printed only in a stamp; worked sample s04 shows it | 3, 8 |
| h23 | outlined, 2 lots; a4_continuation, continuation, round_fail, round_min, units_bad | one lot reported where two print; or 12 rows where 9 print, and the second lot's rows mixed | misreading of an outlined page | 4, 9 |
| h24 | scan_rotated, 2 lots; rev_extends, rev_page, rev_twice, round_fail, round_range, wrap | supplier `PRADESH PHYTOCHEM` for `Pradesh Phytochem Pvt. Ltd.` | written rule missed: the header prints the full name; the comparison ignores case, so only the dropped words cost the item | 3 |
| h06 | scan_no_ocr, 2 lots; fail, rev_extends, rev_page, round_min, units, units_bad | unit `me/L` for `mg/L` | misreading: the agent's own OCR; the page prints `mg/L` clearly | 2, 4 |

Nothing falls in the classes unstated rule, ambiguous wording, grader fault or environment fault. Every Opus trial fails at least one item decided by a written rule (h05 or h24).

The Codex misses are mostly page-reading failures (`Ingreclients` for `Ingredients`, `L` read as `1`, invented or missed lots, a note read into a result row) plus the same traps (h05, h09, h29 in every run). They were not attributed item by item; the Opus set already proves fairness on the shared items.

## Margin

h09 and h29 are one trap: the `≤` lost in a distilled text layer. Every Opus failure includes both. Without them Opus would sit at 28 or 29 of 30 on two trials. The task is fair as written (rule 2: the print decides) and no worked sample shows the exact case; adding one would widen the margin's dependence on reading. If a reviewer asks for that sample, stack more reading features per item at the same time.

## Cheat trials

Red-team prompt `tb3-main/docs/prompts/hack-trial-prompt.md` appended with `--extra-instruction-path`.

| Trial | Model | Reward | What happened |
|---|---|---|---|
| tf4-cheat-codex | GPT-6.1 Sol | 0 | refused the red-team brief (`AgentSafetyRefusalError`), wrote nothing |
| tf4-cheat-opus | Opus 5.5 | invalid | hit the account's usage limit after 75 s; rerun below |
| tf4-cheat-opus-2 | Opus 5.5 | 0 | explored `/app` and `/tests` for 3 min, was stopped by its own safety classifier, reported no exploit and no tool |

## Generator fixes found through these trials

h03 in the earlier build (1j): the retest stamp overlapped the printed word `(Precipitated)`. Fixed in the renderer (`cb01bdf`): a stamp never covers a printed word; test `test_a_stamp_covers_no_printed_word`.

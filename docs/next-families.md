# Next task families: proposal

Written 2026-11-01, after coa-intake reached the bar (Codex 0 of 3, Opus 0 of 3). Five candidate families were researched in parallel; the raw reports with a URL per claim are in the session scratchpad (`research-signals.md`, `research-geometry.md`, `research-inbox.md`, `research-wire.md`, `research-novelty.md`).

## 1. What beat the models, stated so it can be reused

coa-intake did not win because it used PDFs. It won through five mechanisms, and each one can be carried to another medium:

| # | Mechanism | In coa-intake | General form |
|---|---|---|---|
| 1 | A cheap channel that lies | text layer vs pixels | any derived, cached or declared layer that can disagree with the canonical one |
| 2 | The agent must build a reader | 10 samples, 30 hidden items, patching never converges | any task where "reading" needs robust signal or geometry code, not a parser |
| 3 | Stacking | 4 to 6 features per item, 30 items, all or nothing | same |
| 4 | Supersession | revision pages, stamps, later values win | corrections, retries, acks, later messages, later offsets |
| 5 | Exactness by house rules | rounding, units, dates, from a truth engine | same; truth computed from the generator's data, never read back |

What made it fair: rules as data, every feature in a worked sample, truth from the generator, oracle 1 and nop 0, mutants, holdout seeds at 90%. All of that is domain-free already. The only domain-bound part of the builder is docforge, the PDF degradation stage.

One caveat from the novelty check: mechanism 1 alone is not ours. Terminal-Bench 4's `medical-claims-processing` already says the invoice images win over the structured data. Our novelty is the generator plus stacking plus withheld decoders, not the lie by itself.

## 2. The factory change: the medium becomes a plugin

docforge becomes one of several "forges". A forge takes a clean rendering of a generated item and applies routes and overlays with real tools. The pack, plan, gates, fix loop and trials stay the same.

| Forge | Clean form | Routes and overlays | Real tools |
|---|---|---|---|
| docforge (built) | PDF | digital, distilled, outlined, scans with right, wrong or no OCR, rotation, forms; stamps, corrections, watermarks | Ghostscript, OCRmyPDF, pdftk |
| sigforge | WAV from encoded frames | twist, clipping, drift, fading, multipath, DC offset, wrong header rate, dropped samples, channel swap | direwolf gen_packets, minimodem, multimon-ng gen-ng, ebook2cw, sox |
| plotforge | PNG from matplotlib | log, dual and broken axes, overlapping series, legends, anti-aliasing, JPEG, scan | matplotlib, Pillow, docforge's scan route |
| ncforge | G-code from a house post-processor | five controller dialects, modal carry-over, decimal-point modes, subprograms, block delete | the generator itself; LinuxCNC `rs274` as a cross-check |
| byteforge | fixed-width records from a copybook | VB blocks with RDW and BDW, cp037 vs cp1047, packed and zoned signs, ODO, REDEFINES | GnuCOBOL `cobc -fsign=EBCDIC`, Python codecs; JRecord or vgi-fixedformat as cross-check |
| inboxforge | EML thread, xlsx, PDF | quoting styles, forwards with edited quotes, encoded headers, out-of-order dates; planted cached values, 1904 epoch, hidden rows, text numbers | Python email and mailbox, XlsxWriter, LibreOffice headless with forced recalc, docforge |

Two additions the pack needs that coa-intake did not:

- **A withhold list.** Each pack names the decoders the container must not have (direwolf, multimon-ng, minimodem, pycw, gerbonara, pygcode, WebPlotDigitizer) and the container runs offline with no pip. Every CTF write-up found for the signal modes was solved by running a ready decoder; none wrote DSP. Withholding is the whole difference.
- **Truth types.** Integer and text only, or a number with a tolerance stated in the policy. Terminal-Bench rejected tasks whose float truths differed across machines (PR #679).

## 3. The candidates, ranked

Ranked by expected chance of a fair 0 of 3 against both frontier families, then by novelty, then by build cost.

| Rank | Family | Perception lever | Lying channel | Novelty | Model strength evidence | Build cost |
|---|---|---|---|---|---|---|
| 1 | **Signals:** AFSK 1200 AX.25/APRS packet log, then RTTY/Baudot | strong (DSP from scratch) | operator's TNC2 log, a partial decoder transcript, WAV header | new medium; no agent benchmark on modem or CW decoding | EMRB: code agents 84.9% on basic measurement, 21.2% on signal system design | low: direwolf, minimodem, sox are small apt packages |
| 2 | **Plot digitization:** chart image to exact values | strong (pixels to numbers) | embedded data table or CSV that disagrees with the plotted points | new medium for TB; labeled-chart VQA is saturated, unlabeled recovery is not | best MLLM MAPE 5.94% on unlabeled charts; 40 to 60% drops on unlabeled multi-line and stacked | low: matplotlib plus docforge's scan route |
| 3 | **Maker geometry:** G-code in five dialects, shop rules | none (parsing and state) | header comments vs modal state | new for CNC verification; TB4 covers CAD heavily and models are 5 of 5 on most of it | CAD Bench 61 for Opus 5.5; LLMs cannot parse full G-code single-shot (Jignasu 2023) | low to medium: generator owns truth; no open Fanuc or Haas simulator exists, which helps |
| 4 | **Wire formats:** COBOL VB/EBCDIC extract, then X12 850/810 with 997 | none (bytes and spec) | the ASCII CSV export, the header's declared code page | new medium; no eval on copybook data decoding | mixed: COBOLBench 11%, but GPT-6.1 Sol 97.9% on OpenAI's COBOL migration eval | medium: real encoders are GnuCOBOL or JVM |
| 5 | **Mixed inbox:** EML + xlsx + PDF, desk policy decides | none unless the PDF is scanned | planted cached values, pandas defaults, quote strippers | least novel: xlsx and rules packets are in seven TB4 tasks; email threads and cached-value tricks are new | SpreadsheetBench 2 debugging 12%; TB4 foodstuff and glycan 0 of 5 | lowest: reuses docforge and the coa pack shape |

### Why this order

- **Signals first** because it carries the lever that actually defeated Opus three times: the agent has to write robust perception code and generalize it. An expert can do it without the tool: a pure-Python decoder (`micro-aprs`) gets 1010 of the standard test-CD frames, and a 290-line NumPy stack survives 18 dB of noise. A textbook correlator passes clean audio and loses frames under twist, drift and fading; direwolf's own demodulator paper gives the numbers to calibrate the stack against. Morse and DTMF are too well known (Goertzel is textbook) and stay sub-features.
- **Plot digitization second** because the evidence of model weakness is the clearest of the five and the build is the cheapest after inbox. The risk is design, not tooling: items must not be solvable by OCR of tick labels alone, so the plotted values fall between ticks, axes are log or broken, series overlap, and the policy fixes a tolerance.
- **Geometry third** despite being the house domain. It is a parsing task, and models are strong parser writers. Its strength is the dialect splits a machinist knows and a model half-knows: Fanuc's decimal-point mode (X1000 is 1 mm or 1000 mm), G28.1 meaning different things on Mach3 and LinuxCNC, G53 ignored in G91 on Fanuc, stale H after G43. It should be built, but after a pilot proves the stack reaches 0 of 3.
- **Wire formats fourth** for the same reason: a frontier agent writes a COMP-3 decoder in minutes. The 0 of 3 case rests on ODO, REDEFINES, code-page lies and supersession interacting across 30 records. A cheap pilot exists: the CSOAI copybook decoding corpus (41 copybooks, published 2026-09-28) has no model scores yet.
- **Inbox last** as a flagship, but first as a volume family: it reuses the most machinery, every quirk is in a public standard, and if text-only proves too easy the scanned PDF from docforge restores the pixel lie.

## 4. Per-task frontier results worth knowing

From the Harbor hub, 5 trials each, Opus 5.5 max / GPT-6 Astra max (row ids in `research-novelty.md`):

- Audio: `satb-audio-transcription` 5/5 and 5/5. `music-harmony` 0/5 and 0/5.
- CAD: `cad-model`, `freecad-platform-drawing`, `hof-topology`, `wdm-design` 5/5 and 5/5. `freecad-impeller` 0/5 and 0/5.
- Rules packets: `medical-claims-processing`, `freight-dispatch-shift`, `cargo-flight-dispatch`, `foodstuff-beta-activity`, `glycan-ms2` 0/5 and 0/5. `gsea-proteomics` 5/5 and 0/5.
- `vba-userform-port` is 0/5 for Opus but 1/5 for Astra max, so it leaves the "both fail" list; `music-harmony` joins it.

The hard ones share our shape: dense written rules, supersession, exact output, several corrections that compound. None of them uses a generator, which is what lets us make thirty of them.

## 5. How to find new kinds: the domain-master mine

A domain qualifies when it has all five:

1. written, exacting rules: SOPs, standards, implementation guides, certification blueprints
2. messy inputs made by many hands or many tools
3. a lie between two channels that practitioners already complain about
4. a computable truth
5. real tools that produce the degradation

The feature lists come for free from four places, and this research confirmed each:

- **Parser bug trackers.** Every closed bug in direwolf, multimon-ng, minimodem, gerbv, pygerber, pygcode, openpyxl, pandas, python-hl7, hl7apy and pyx12 is a generator feature with a real cause. The reports list 10 to 15 per medium.
- **Practitioner gotcha lists.** WB2OSZ's demodulator papers, N1VG's note that the AX.25 spec text on bit stuffing is wrong, Practical Machinist crash threads, EuSpRIG spreadsheet horror stories, Mirth's HL7 error list, IBM's sign-nibble tables.
- **Standards and their deprecated-feature chapters.** Ucamco's Gerber chapter 8, Haas settings 15 and 77, RFC 3676 quoting depth, IBM NUMPROC.
- **Conformance corpora.** The WA8LMF TNC test CD for packet, the CSOAI copybook corpus, Ucamco's PEG grammar.

Screening protocol for a new domain, before any build: one hour to confirm the tools run headless in a container; the hub per-task table for the medium; the withhold list; then the factory's existing gates.

## 6. Recommendation

Pilot **signals** now: a `packet-log` pack (AFSK 1200, AX.25/APRS) with sigforge, 10 rules, 15 features, 30 hidden items. The reference is the fairness proof: if the fix loop cannot write a decoder that passes 30 of 30 with the truth in hand, the stack is too deep and gets turned down before any trial. Then the same cheap screen and frontier trials as coa-intake.

Run **plot digitization** as the second pilot in parallel if time allows; it shares the scan route and the image-reading verification already built for coa-intake.

Build **geometry** third, with Alex writing the shop rules, since the research found no open Fanuc or Haas simulator and the dialect traps are exactly the ones a machinist knows.

Keep **wire formats** and **inbox** as the volume families once the forge plugin exists.

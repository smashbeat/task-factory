# Task builder: design

Goal: a builder that produces Terminal-Bench tasks, not a checker of finished ones. It takes a domain brief and produces a complete task: the generator, the instruction and policy, the reference solution, the verifier and the Harbor task directory. It checks quality, difficulty and fairness at each stage while it builds. A judge sends a failure back to the stage that caused it, and a bad task stops before the expensive stages.

## Task family

The first family is **documents in, rules decide**, the shape coa-intake proved: messy documents, a written policy, a structured output per item, graded exactly. One family keeps the machinery reusable. Invoices, lab certificates, shipping manifests, insurance claims and customs declarations are all domains of it.

## Parts

1. **docforge** (domain-free). It turns a clean, born-digital PDF into routes: digital, distilled, outlined, scan with a right, wrong or missing OCR layer, sideways scan, form fields with a stored value that differs from what prints. It adds overlays: stamp, freetext correction, watermark, white decoy. Ported from coa-intake's `gen2.py`.
2. **Domain pack** (one per domain). It holds:
   - the data model
   - **rules as data:** each rule has an id, text and the fields it decides
   - **features:** each says which rule it exercises and the signature its violation leaves in a diff
   - the truth engine, which can switch off any single rule
   - house styles: layouts, fonts, date formats, producer metadata
   - a renderer to a clean PDF

   The policy text, the instruction, the samples and the attribution profile are all **produced from the pack**, never written by hand. That is what keeps instruction, tests and attribution from drifting apart.
3. **Generator driver** (domain-free).
   - Composition is drawn per seed, so the house, route and features are random per item (fixing coa-intake's fixed composition).
   - Samples are planned so every feature appears in at least one worked sample.
   - Hidden items combine features.
   - Truth comes from the truth engine, never from reading the rendered document.
4. **Builder pipeline:** stages with gates, a judge that routes failures, retries with a budget, a run log, and early stop.
5. **Authoring agents:** Claude Code run headless (`claude -p`) in a workspace. They write a domain pack from a brief, the reference solution, and fixes the judge asks for.

## Stages and gates

| Stage | Produces | Gate checks | Cost | On failure, back to |
|---|---|---|---|---|
| 0 Brief | domain brief | the brief names a decision, output fields and at least 6 rules | none | brief |
| 1 Pack | domain pack | schema valid; every rule exercised by at least 1 feature; every feature linked to a rule; truth engine runs on 50 random items | seconds | pack |
| 2 Spec | policy, instruction, sample plan | every rule appears in the policy; every feature appears in at least 1 sample; ambiguity probe: models answer edge cases from the policy alone, and disagreement with truth fails the rule | minutes, cents | pack (rule wording) |
| 3 Generator | corpus per seed | same seed gives the same truth; different seeds differ in composition; at least 3 house styles used; producer metadata varies; **rule mutation:** switching off each rule changes the truth of at least 1 hidden item | seconds | pack or driver |
| 4 Reference | reference solution | oracle passes every item on N seeds; nop scores 0; time per item under the limit with headroom | minutes | reference |
| 5 Cheap screen | one mid-tier trial | must fail | 20 min | design (too easy) |
| 6 Frontier | staged trials, one family at a time | all fail; checkpoints every 30 min run the hidden verifier on a snapshot and stop a trial that already passes | hours | design |
| 7 Attribution | failure labels, seed replay | every trial fails at least 1 rule-decided item; nothing unexplained; replay on fresh seeds holds | seconds | pack (unstated rule) or design |
| 8 Cheat | adversarial trials | reward 0 | 1 to 2 h | environment |

## The judge

Each gate returns a typed verdict: `pass`, `warn` or `fail(back_to, evidence, fix)`.
- **Deterministic gates** state the fix themselves, for example "feature stamp_retest is in no sample: add it to the sample plan".
- **Model-written fixes** go to an authoring agent with the evidence, and that stage reruns.
- **Retry limit:** two retries per stage. After that the task stops and a person decides.
- **Paid stages:** stages 5 to 8 spend real agent time and run only with `--trials` and Alex's go-ahead.

## Build order

1. docforge, the generator driver, the coa domain pack ported, and gates 1 to 3 deterministic. This proves the generator end to end on a known domain.
2. Domain pack authoring by agent from a brief, plus the judge loop. This proves new domains.
3. Reference authoring and the oracle and nop gate in Docker.
4. Harbor trials: cheap screen, staged frontier with checkpoints, attribution (built), seed replay, cheat.

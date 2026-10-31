# Quality, difficulty, fairness: a gated task factory

Follow-up to the Klavis call. Three properties came up: the quality of a task, its difficulty, and its fairness. This note says how to assure each one, how to build tasks fast with a generator, and how to check the three properties at gates during the build, so a bad task dies early and cheaply instead of after a full round of frontier trials.

Everything marked **seen** happened in my own runs. Everything else is a proposal.

## 1. Three properties, three kinds of evidence

They are not the same kind of thing, and that decides how each can be checked.

| Property | Question | Best evidence | Can a judge read it off the task? |
|---|---|---|---|
| Quality | Does the task do what it claims, every time? | Deterministic checks: oracle 1, nop 0, reference on fresh seeds, verifier mutation | Partly. Code checks do most of it. |
| Difficulty | Do strong agents fail? | Agent trials. Only measured, never judged | No. A judge can guess; only runs measure. |
| Fairness | When they fail, is it their fault? | Attribution of each failed check to a written rule | Only with the trial outputs in front of it |

The lesson from my runs: a rubric that reads the task is good at quality and weak at fairness and difficulty.
- **Seen:** the capsule planner's failures rested on a rule I never wrote. A human reviewer found it, not a rubric. Once the rule was written, Codex solved it in 14.5 minutes.
- **Seen:** Preference Model's audit of Terminal-Bench 4 found 41 of 65 tasks grading honest work on unstated rules. Those tasks shipped through review. After the fixes, Sonnet 5.5 went from 62.8% to 89.2%.

So fairness has to be judged on failures, not on task text.

## 2. Definitions that can be checked

- **Quality:** the reference passes on every seed, the empty solution fails, results are deterministic, the verifier is isolated from the agent, and every rule in the instruction is actually tested.
- **Difficulty:** strong agents from at least two model families fail every trial within the time budget, and the cheat trials score 0.
- **Fairness:** every check that decides a failure traces to a sentence in the instruction or a worked sample. A capable expert who reads only the instruction and the environment would produce the expected answer. Every hidden case was solved by at least one trial, so none is out of reach. **Seen:** in coa-intake, every hidden certificate was read correctly by at least one of six trials.

## 3. Building fast: the generator

A generator turns one task into a family of tasks. coa-intake's generator (`gen2.py`, about 1,200 lines) is the working example.

**How it works.** A seeded model of the domain: a certificate is built as data first. The feature knobs (scan, wrong OCR, rotation, form field mismatch, revision page, stamp) are applied. The truth comes from the policy engine on that data, never from reading the rendered PDF. Then a renderer produces the document.

**What it buys:**
- **A free, exact answer key.** The reference's own reading quirks can't leak into the truth.
- **Fresh seeds for contamination-free variants.** **Seen:** reference 185 of 185 across five seeds.
- **A difficulty knob.** Turn features on or off to make a curriculum.
- **Granular reward.** A score per certificate or per field comes for free.
- **Cheap replay** (see gate 6): an agent's finished program can be rerun on new seeds in seconds.

**Where it breaks:**
- **Fingerprinting.** **Seen:** Opus solved v1 in 5 hours by recognising the generator (one layout, one font set, the producer string) and rebuilding it. Fix: several house styles, realistic producer strings, fonts the container lacks. It needs a gate (gate 2).
- **Variants aren't diversity.** In gen2 the seed changes the content, but the house, route and features per certificate ID stay fixed. Next step: randomise the composition too.
- **Synthetic layouts.** The production routes are real tools (Ghostscript, OCRmyPDF, form appearances), but the layouts are invented. Mixing in real documents with the details removed closes the gap.

**How to build tasks fast.** A person picks the domain and writes the rules: that's the taste, and the part that makes difficulty real. Agents write the generator, the reference and the verifier under the gates below. The rules are stored as data, so the instruction, the samples and the tests are all produced from one source. That alone removes most instruction-to-test drift.

## 4. The gated pipeline

Gates are ordered by cost, so the cheapest check that can kill a task runs first. Each gate's judge returns a typed verdict: pass, or return to a named stage with evidence and a proposed fix. A person approves fairness rulings; the judge proposes them.

| Gate | Checks | Cost | Fails back to |
|---|---|---|---|
| 0 Proposal | Proposal rubric; novelty against existing tasks (embedding dedupe); is the difficulty essential rather than incidental | Minutes, cents | Idea |
| 1 Spec | Fairness lint and ambiguity probe (below) | Minutes, under $1 | Spec |
| 2 Generator | Reference passes on N seeds; determinism; time headroom; fingerprint audit | Minutes | Generator |
| 3 Verifier | Static checks, oracle 1, nop 0, verifier mutation, implementation rubric | About 30 min | Verifier or spec |
| 4 Cheap screen | One mid-tier agent, short cap | 20 min, about $1 | Design: too easy |
| 5 Frontier, staged | Sequential trials with checkpoints | Hours, $1 to $21 a trial | Design or spec |
| 6 Attribution | Every failure classified; seed replay | Minutes | Spec, verifier or design |
| 7 Cheat | One adversarial trial per family | 1 to 2 h | Environment |
| 8 Human | Sample review of the evidence pack | 15 min | Any |

### Gate 1: catch unfairness before anything is built

- **Traceability matrix.** Every test assertion maps to a sentence in the instruction or a worked sample. An assertion with no source is an unstated rule. With rules stored as data, this check is mechanical.
- **Ambiguity probe.** Give 3 models from different families only the instruction, plus 20 edge cases drawn from the generator. Ask each for the expected answer. Where they disagree with each other or with the truth, the rule is ambiguous: fix the wording before building.
- **Seen, and what this gate would have saved:** the capsule planner's missing rule is exactly what the matrix flags. It was found by a reviewer after the full trial rounds.

### Gate 2: fingerprint audit

Train a quick classifier, or ask a model, to tell generated documents from real ones, or to tell them apart by house style. If it can predict the generator's hidden choices from surface features (fonts, producer strings, coordinates), so can an agent. **Seen:** this was the v1 hole, found only after a 5-hour Opus solve.

### Gate 3: verifier mutation

Remove one rule at a time from the reference and run the verifier. Each mutant must fail, which proves every rule is tested. The reverse check also matters: answers that are right but formatted differently must still pass, so the task doesn't grade formatting.

### Gate 4: cheap difficulty screen

One trial with a mid-tier agent and a 20-minute cap. If it passes, the task is too easy and nothing more is spent. **Seen:** my first domains (label compliance and overage math, a speaker crossover, a legacy-engine retirement) were all solved, the supplement tasks in 8 to 20 minutes. Each would have died here for about a dollar instead of a full round of frontier trials.

### Gate 5: staged frontier trials with checkpoints

- **Sequential, fail fast.** The criterion is 0 of 3, so one pass ends the task. Run one trial per family first, and run the rest in parallel only after both fail.
- **Mid-trial checkpoints.** Every 30 minutes, snapshot the agent's work and run the hidden verifier on it, out of band and never visible to the agent. If a snapshot already passes, stop: the task is solvable. If the score per item climbs steadily toward full, raise a warning and let a person decide.
- **Seen, costs:** on coa-intake, Codex trials ran 47 to 53 minutes and Opus 5.5 trials 3 to 7 hours. On a comparable task I reran, a Codex trial cost $1.35 and Opus trials $10 to $21. The Opus v1 solve took 5 hours; checkpoints would have shown it closing in well before the end.

### Gate 6: failure attribution (the fairness judge)

For each failed trial and each failed item, the judge sees the instruction, the samples, the expected value and the agent's value. It classifies the failure as one of:
- written rule missed
- misreading
- unstated rule
- ambiguous wording
- grader fault
- environment fault

**Pass condition:** every trial fails at least one item decided by a written rule, and nothing falls in the last three classes.
- **Seen:** coa-intake's README failure table is this classification done by hand: revision pages, retest stamps, continuation pages and footnote marks, each tied to a rule number.
- **Seed replay:** rerun each agent's finished program on 5 fresh seeds. That costs seconds and no new agent run. It shows whether the failure is robust or one seed's bad luck. **Seen:** local reruns of each agent's program reproduced the verifier's failures exactly. A task Opus failed at 28 of 30 has a thin margin, and replay measures it.

### Calibrating the judges

A judge is only useful if its own error rate is known.
- **Fairness judge:** the Terminal-Bench 4 audit gives about 240 labelled findings (unstated rule, ambiguity, grader fault, genuine) to measure it against before trusting it.
- **Report:** precision on "unstated rule" and the rate of fair tasks wrongly sent back. Route low-confidence verdicts to a person.
- **Typed verdicts:** a decision model that returns calibrated probabilities fits this step better than free text.

## 5. Risks

- **Overfitting to today's models.** A task tuned until Opus 5.5 fails can be hard for idiosyncratic reasons. Require failures across two families, prefer rule-decided failures, and track how long the difficulty survives new releases.
- **Goodhart on the judge.** If tasks are revised until the judge passes them, the judge gets learned. Keep a held-out human review sample and rotate the judge's model.
- **Generator monoculture.** Many tasks from one generator share blind spots. Randomise composition, not only content, and mix in real documents.
- **Cost of the gates themselves.** Gates 0 to 4 cost dollars, gate 5 tens of dollars. The aim is to spend the expensive gate only on tasks that already survived the cheap ones.

## 6. What I would build first

1. Rules as data, producing the instruction, the samples and the test assertions from one source, with the traceability matrix (gate 1).
2. Verifier mutation (gate 3), because it's cheap and catches untested rules.
3. Checkpointed trials with out-of-band verification (gate 5), because that's where the hours go.
4. The attribution judge, calibrated on the Terminal-Bench 4 labels (gate 6).

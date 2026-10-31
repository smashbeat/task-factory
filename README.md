# Task Factory

Gates for agent benchmark tasks. A task is worth shipping when three things hold, and each needs a different kind of evidence:

- **Quality:** the task does what it claims, every time. Checked in code: oracle, nop, static checks, implementation rubric.
- **Difficulty:** strong agents fail. Only measured by running them, never judged from the task text.
- **Fairness:** when they fail, it is their fault. Judged on the failures themselves: every failure is traced to a written rule or to the page.

The gates run cheapest first and stop at the first failure. A failing gate names the stage the task goes back to: spec, generator, verifier, environment or design.

## What runs today

`taskfactory check` reads a task's evidence pack (the generator's manifest, the trials Harbor left behind, static checks and rubric runs) and runs four gates:

| Gate | Checks |
|---|---|
| Quality | oracle reward 1, nop reward 0, static checks, every implementation-rubric run |
| Difficulty | every standard trial fails; at least two agent families; warns when the best trial is within 10% of a pass |
| Fairness | every trial fails at least one item on a written rule; cited rules exist in the policy; flags rules no worked sample shows; flags items no trial solved |
| Cheat | cheat trials score 0 |

**Failure attribution** is the core of the fairness gate, and it works without model calls. The generator records which features it put on each item. The task profile (`factory.toml`) gives each feature a signature: what the verifier's diff looks like when an agent breaks the rule behind it. Each diff is then:
- **rule-decided** if it matches a signature
- **reading** if the page explains it (scanned routes, overlays, or text that is right apart from garbled, added or dropped characters)
- **unexplained** otherwise. Only that residue needs a model or a person to judge.

On coa-intake it reproduces the hand-made failure table exactly: 18 rule-decided failures across six trials, the rest reading misses, nothing unexplained. It also found something the hand analysis didn't: four of the rule-triggering features (revision page, second revision, retest stamp, A4 continuation) appear in no worked sample.

## Use

```bash
uv venv -p 3.13 && uv pip install -e '.[dev]'
uv run pytest
uv run taskfactory check tests/fixtures/coa-intake --html out/coa-intake.html
```

Exit code 0 means ship or ship with warnings, and 1 means send back. `--keep-going` runs every gate even after one fails.

## Evidence pack layout

```
manifest.json                 generator record: id, route, house, features per hidden item and sample
policy.md                     the task's numbered rules
factory.toml                  the task profile: decision fields, reading routes and features, signatures
results/static-checks.txt     PASS or FAIL per check
results/rubric/*.json         one implementation-rubric run per file
results/<job>/<trial>/        reward.txt, ctrf.json, trial.json; the job name says standard, cheat, oracle or nop
```

## Not built yet

These follow `docs/design.md`:
- **Spec gate:** trace each assertion to a sentence of the instruction, plus the ambiguity probe across model families.
- **Generator fingerprint audit.**
- **Verifier mutation.**
- **Cheap mid-tier screen.**
- **Checkpointed frontier trials:** verify snapshots out of band and stop a trial that is already passing.
- **Seed replay** of each agent's finished program.
- **A calibrated judge for unexplained failures.**

# Trial harness

The scripts the pilot logs in `docs/` cite. They wrap [Harbor](https://github.com/harbor-framework/harbor) for the runs and the pack's reference image for the replays. Everything they write goes under `out/`, which git ignores.

| Script | What it does |
|---|---|
| `harbor_task.sh TASK JOBS NAME [agent args]` | one Harbor job on a task directory; prints reward, test summary, exception type and failed item ids |
| `frontier_chain.sh TASK JOBS CODEX_JOB OPUS_JOB` | Codex GPT-6.1 Sol at xhigh, then Claude Code Opus 5.5 at max, one after the other |
| `replay_agent.sh TRIAL BUILD ID...` | reruns an agent's saved program on hidden packages in the reference image and diffs each output against the truth |
| `render_page.py PKG NAME OUT.png [dpi]` | renders a page, loose or attached to an email, to look at what the agent saw |
| `layer_dump.py PKG REGEX` | prints each page's text-layer size and the layer lines matching a pattern |

The order that worked, per pack and seed:

1. `uv run taskfactory build packs/<pack> --seed 1 --out out/build-<pack>-1 --docker` builds the corpus, runs the reference, assembles the Harbor task directory and reports every gate.
2. `harbor_task.sh` with no agent args (the oracle, must score 1) and with `--agent nop` (must score 0).
3. A cheap screen: Claude Code on Sonnet 5.5 with `--timeout-multiplier 0.25`, a 2 h cap. A task that falls here costs a few dollars, not an afternoon.
4. `frontier_chain.sh`, one trial per family. Second and third runs only if the first pair fails.
5. For every miss, `replay_agent.sh`. A miss that replays is read from the program and the page, with `render_page.py` and `layer_dump.py`, and written into the pack's pilot log with its rule.

Two things Harbor does that cost me time: it writes every digit 1 as `[REDACTED]` in a trial's files when any value passed with `--ae` is `1` (the scripts undo it), and `tests/` is read from disk at verification time, so the task tree must not move while a trial runs.

Never run a second heavy Docker job beside a trial. The verifier's per-item limit is wall-clock on two CPUs, and a slow replay next to it turns a pass into a kill.

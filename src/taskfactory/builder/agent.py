"""Authoring agents: headless Claude Code, each in its own workspace, fixing what a gate sent back.

The agent sees only its workspace: the file to fix, the policy, the failing items with their expected output,
and a check script that runs the fix in the task's software. It may edit the file and run the check, nothing
else. Its fix is accepted only if the gate passes again on this build and on a held-out seed it never saw, so a
fix that special-cases the failing items is caught.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .pack import Domain

REFERENCE_PROMPT = """You maintain the reference solution of a benchmark task. It is `intake.py` in this directory.
It must implement `policy.md` exactly, for every {item} the generator can draw.

The reference just failed on the {item}s in `failing/`. The {item}s in `passing/` already read correctly and must
keep reading correctly: a fix that breaks one of them is rejected. For each one you have the input (`ID.{ext}`, `ID.spec.json`),
the expected output (`ID.expected.json`) and the differences the verifier reported (`ID.diff.txt`).

Fix `intake.py` so it reads these correctly. Rules:
- Fix the general cause. Never special-case an id, a file name, a lot number or any value from these files:
  your fix is tested again on a held-out set of {item}s you have not seen, and a fix that only works here fails.
- Follow `policy.md`. If the expected output looks wrong against the policy, do not change the code to match it:
  write the reason in `DISPUTE.md` and stop. That sends the {item} back to the generator.
- Run `{check}` to test. It runs your `intake.py` on every {item} in `failing/` and `passing/` in the task's own
  software and prints what still differs. Keep going until it prints no differences, or until you write DISPUTE.md.
- Keep the runtime under {limit} seconds per {item}.
When done, reply with one paragraph: what was wrong and what you changed."""

CHECK = """#!/bin/sh
# Runs intake.py on every failing and passing item inside the task's software image and prints what differs.
# Lives outside the agent's workspace, read-only; the workspace is mounted read-only and the container has no network.
docker run --rm --network none -e OMP_THREAD_LIMIT=1 -v "{ws}:/w:ro" -w /w {image} python3 -I -c '
import json, subprocess, sys
sys.path.insert(0, "/w")
import compare
from pathlib import Path
bad = 0
for spec in sorted(Path("failing").glob("*.spec.json")) + sorted(Path("passing").glob("*.spec.json")):
    i, d = spec.name[: -len(".spec.json")], spec.parent
    out = Path("/tmp") / (i + ".json")
    p = subprocess.run(["python3", "intake.py", str(d / (i + ".{ext}")), str(spec), str(out)], capture_output=True, text=True, timeout={limit})
    if p.returncode != 0:
        bad += 1
        print(i, "exit", p.returncode, p.stderr[-600:])
        continue
    diff = compare.compare_files(out, d / (i + ".expected.json"))
    bad += bool(diff)
    if diff or d.name == "failing":
        print(i, "(was passing, now broken)" if diff and d.name == "passing" else "",
              "OK" if not diff else "\\n  ".join([""] + diff[:15]))
print("all right" if not bad else f"{{bad}} still differ")
'
"""


def make_workspace(pack: Domain, builds: Path | list[Path], attempt: int,
                   start: Path | None) -> tuple[Path, list[str]]:
    """The agent's workspace: the file to fix (the latest candidate, else the pack's reference), the policy, the
    failing items with their differences, and the passing items as a regression set. With several seeds, item
    ids are prefixed with the seed so they stay apart."""
    builds = [Path(builds)] if isinstance(builds, (str, Path)) else [Path(b) for b in builds]
    # The workspace lives outside the build tree, so nothing near it holds hidden answers.
    ws = Path(tempfile.mkdtemp(prefix=f"tf-fix-reference-{attempt}-"))
    shutil.copy(start or pack.root / "task" / "solution" / "intake.py", ws / "intake.py")
    shutil.copy(pack.root / "task" / "tests" / "compare.py", ws / "compare.py")
    shutil.copy(builds[0] / "policy.md", ws / "policy.md")
    failing = []
    for build in builds:
        prefix = f"{json.loads((build / 'manifest.json').read_text())['seed']}-" if len(builds) > 1 else ""
        for r in json.loads((build / "reference.json").read_text()):
            i, n = r["id"], prefix + r["id"]
            d = ws / ("passing" if r["ok"] else "failing")
            d.mkdir(exist_ok=True)
            shutil.copy(build / pack.ext / f"{i}.{pack.ext}", d / f"{n}.{pack.ext}")
            shutil.copy(build / "specs" / f"{i}.json", d / f"{n}.spec.json")
            shutil.copy(build / "truth" / f"{i}.json", d / f"{n}.expected.json")
            if not r["ok"]:
                (d / f"{n}.diff.txt").write_text("\n".join(r["diffs"]))
                failing.append(n)
    return ws, failing


def fix_reference(pack: Domain, build: Path | list[Path], image: str, attempt: int, limit: int = 120,
                  model: str | None = None, budget_usd: float = 5.0, start: Path | None = None) -> dict:
    builds = [Path(build)] if isinstance(build, (str, Path)) else [Path(b) for b in build]
    ws, failing = make_workspace(pack, builds, attempt, start)
    checker = Path(tempfile.mkdtemp(prefix=f"tf-checker-{attempt}-"))
    check = checker / "check.sh"
    check.write_text(CHECK.format(image=image, limit=limit, ws=ws.resolve(), ext=pack.ext))
    check.chmod(0o555)
    checker.chmod(0o555)
    digest = hashlib.sha256(check.read_bytes()).hexdigest()
    prompt = REFERENCE_PROMPT.format(item=pack.item, limit=limit, check=check.resolve(), ext=pack.ext)
    # Edits are confined to the workspace (the working directory); the only command allowed is the checker,
    # by absolute path, which sits outside the workspace where the agent cannot change it.
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits",
           "--allowed-tools", *[f"{t}(/{ws.resolve()}/**)" for t in ("Read", "Edit", "Write", "Glob", "Grep")],
           f"Bash({check.resolve()})",
           "--disallowed-tools", "WebFetch", "WebSearch",
           *[f"{t}(/{b.resolve()}/**)" for b in builds for t in ("Read", "Glob", "Grep", "Edit", "Write")],
           *[f"{t}(/{pack.root.resolve()}/**)" for t in ("Read", "Glob", "Grep", "Edit", "Write")],
           "--max-budget-usd", str(budget_usd)]
    if model:
        cmd += ["--model", model]
    p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=3 * 3600)
    tampered = hashlib.sha256(check.read_bytes()).hexdigest() != digest
    try:
        reply = json.loads(p.stdout)
    except json.JSONDecodeError:
        reply = {"result": p.stdout[-2000:], "is_error": True}
    disputed = (ws / "DISPUTE.md").exists()
    return {
        "workspace": str(ws),
        "failing": failing,
        "summary": reply.get("result", ""),
        "cost_usd": reply.get("total_cost_usd"),
        "error": bool(reply.get("is_error")) or p.returncode != 0 or tampered,
        "tampered": tampered,
        "disputed": disputed,
        "dispute": (ws / "DISPUTE.md").read_text() if disputed else None,
        "fixed_file": str(ws / "intake.py"),
    }

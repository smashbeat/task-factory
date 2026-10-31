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
from pathlib import Path

from .pack import Domain

REFERENCE_PROMPT = """You maintain the reference solution of a benchmark task. It is `intake.py` in this directory.
It must implement `policy.md` exactly, for every {item} the generator can draw.

The reference just failed on the {item}s in `failing/`. For each one you have the input (`ID.pdf`, `ID.spec.json`),
the expected output (`ID.expected.json`) and the differences the verifier reported (`ID.diff.txt`).

Fix `intake.py` so it reads these correctly. Rules:
- Fix the general cause. Never special-case an id, a file name, a lot number or any value from these files:
  your fix is tested again on a held-out set of {item}s you have not seen, and a fix that only works here fails.
- Follow `policy.md`. If the expected output looks wrong against the policy, do not change the code to match it:
  write the reason in `DISPUTE.md` and stop. That sends the {item} back to the generator.
- Run `{check}` to test. It runs your `intake.py` on every failing {item} in the task's own software and prints
  what still differs. Keep going until it prints no differences, or until you write DISPUTE.md.
- Keep the runtime under {limit} seconds per {item}.
When done, reply with one paragraph: what was wrong and what you changed."""

CHECK = """#!/bin/sh
# Runs intake.py on every failing item inside the task's software image and prints what differs.
# Lives outside the agent's workspace, read-only; the workspace is mounted read-only and the container has no network.
docker run --rm --network none -e OMP_THREAD_LIMIT=1 -v "{ws}:/w:ro" -w /w {image} python3 -I -c '
import json, subprocess, sys
sys.path.insert(0, "/w")
import compare
from pathlib import Path
bad = 0
for spec in sorted(Path("failing").glob("*.spec.json")):
    i = spec.name[: -len(".spec.json")]
    out = Path("/tmp") / (i + ".json")
    p = subprocess.run(["python3", "intake.py", f"failing/{{i}}.pdf", str(spec), str(out)], capture_output=True, text=True, timeout={limit})
    if p.returncode != 0:
        bad += 1
        print(i, "exit", p.returncode, p.stderr[-600:])
        continue
    d = compare.compare_files(out, Path("failing") / (i + ".expected.json"))
    bad += bool(d)
    print(i, "OK" if not d else "\\n  ".join([""] + d[:15]))
print("all right" if not bad else f"{{bad}} still differ")
'
"""


def fix_reference(pack: Domain, build: Path, image: str, attempt: int, limit: int = 120,
                  model: str | None = None, budget_usd: float = 5.0) -> dict:
    build = Path(build)
    ws = build / f"fix-reference-{attempt}"
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "failing").mkdir(parents=True)
    shutil.copy(pack.root / "task" / "solution" / "intake.py", ws / "intake.py")
    shutil.copy(pack.root / "task" / "tests" / "compare.py", ws / "compare.py")
    shutil.copy(build / "policy.md", ws / "policy.md")
    failing = [r for r in json.loads((build / "reference.json").read_text()) if not r["ok"]]
    for r in failing:
        i = r["id"]
        shutil.copy(build / "pdf" / f"{i}.pdf", ws / "failing" / f"{i}.pdf")
        shutil.copy(build / "specs" / f"{i}.json", ws / "failing" / f"{i}.spec.json")
        shutil.copy(build / "truth" / f"{i}.json", ws / "failing" / f"{i}.expected.json")
        (ws / "failing" / f"{i}.diff.txt").write_text("\n".join(r["diffs"]))
    checker = build / f"checker-{attempt}"
    if checker.exists():
        shutil.rmtree(checker)
    checker.mkdir()
    check = checker / "check.sh"
    check.write_text(CHECK.format(image=image, limit=limit, ws=ws.resolve()))
    check.chmod(0o555)
    checker.chmod(0o555)
    digest = hashlib.sha256(check.read_bytes()).hexdigest()
    prompt = REFERENCE_PROMPT.format(item=pack.item, limit=limit, check=check.resolve())
    # Edits are confined to the workspace (the working directory); the only command allowed is the checker,
    # by absolute path, which sits outside the workspace where the agent cannot change it.
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits",
           "--allowed-tools", *[f"{t}(/{ws.resolve()}/**)" for t in ("Read", "Edit", "Write", "Glob", "Grep")],
           f"Bash({check.resolve()})",
           "--disallowed-tools", "WebFetch", "WebSearch",
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
        "failing": [r["id"] for r in failing],
        "summary": reply.get("result", ""),
        "cost_usd": reply.get("total_cost_usd"),
        "error": bool(reply.get("is_error")) or p.returncode != 0 or tampered,
        "tampered": tampered,
        "disputed": disputed,
        "dispute": (ws / "DISPUTE.md").read_text() if disputed else None,
        "fixed_file": str(ws / "intake.py"),
    }

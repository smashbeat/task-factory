"""Runs inside the task's environment image: the reference solution on every item. No answers are mounted.

python3 -I reference_main.py SOLUTION_FILE INPUT_DIR OUT_DIR [WORKERS] [EXT] [LIMIT]
INPUT_DIR holds ID.EXT (pdf by default; a folder when the pack says so) and ID.spec.json (read-only); OUT_DIR
receives ID.json and ID.run.json. LIMIT is the verifier's seconds per item (120 by default).
Scoring happens outside the container, so the solution never has the truth within reach.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

SOL = IN = OUT = None
EXT = "pdf"
LIMIT = 120
PARALLEL_CAP = 900  # contention only: the real limit is checked alone afterwards


def _one(args: tuple[str, float]) -> dict:
    item_id, cap = args
    t0 = time.time()
    try:
        p = subprocess.run(["python3", str(SOL), str(IN / f"{item_id}.{EXT}"), str(IN / f"{item_id}.spec.json"),
                            str(OUT / f"{item_id}.json")], capture_output=True, text=True, timeout=cap,
                           env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        rc, err = p.returncode, p.stderr[-400:]
    except subprocess.TimeoutExpired:
        rc, err = 137, "killed at the time limit"
    return {"id": item_id, "returncode": rc, "stderr": err, "seconds": time.time() - t0}


def main() -> None:
    global SOL, IN, OUT, EXT, LIMIT
    SOL, IN, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    EXT = sys.argv[5] if len(sys.argv) > 5 else "pdf"
    LIMIT = int(sys.argv[6]) if len(sys.argv) > 6 else 120
    ids = sorted(p.stem for p in IN.glob(f"*.{EXT}"))
    with Pool(workers) as pool:
        runs = pool.map(_one, [(i, PARALLEL_CAP) for i in ids])
    by_id = {r["id"]: r for r in runs}
    for r in sorted(runs, key=lambda r: -r["seconds"])[:3]:
        alone = _one((r["id"], LIMIT))
        by_id[r["id"]] = {**alone, "seconds_parallel": r["seconds"]}
    (OUT / "runs.json").write_text(json.dumps([by_id[i] for i in ids], indent=1))


if __name__ == "__main__":
    main()

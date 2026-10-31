"""Runs inside the task's environment image: the reference solution on every item, scored like the verifier.

python3 -I reference_main.py TASK_TESTS_DIR SOLUTION_FILE BUILD_DIR [WORKERS]
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from multiprocessing import Pool
from pathlib import Path

TESTS = SOL = BUILD = None
LIMIT = 120


def _one(item_id: str) -> dict:
    sys.path.insert(0, str(TESTS))
    import compare

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out.json"
        spec = Path(td) / "spec.json"
        spec.write_text((BUILD / "specs" / f"{item_id}.json").read_text())
        t0 = time.time()
        try:
            p = subprocess.run(["python3", str(SOL), str(BUILD / "pdf" / f"{item_id}.pdf"), str(spec), str(out)],
                               capture_output=True, text=True, timeout=LIMIT)
            rc, err = p.returncode, p.stderr[-400:]
        except subprocess.TimeoutExpired:
            rc, err = 137, "killed at the time limit"
        secs = time.time() - t0
        if rc != 0 or not out.exists():
            return {"id": item_id, "ok": False, "seconds": secs, "diffs": [f"exit {rc}: {err}"]}
        truth = Path(td) / "truth.json"
        truth.write_text((BUILD / "truth" / f"{item_id}.json").read_text())
        diffs = compare.compare_files(out, truth)
        return {"id": item_id, "ok": not diffs, "seconds": secs, "diffs": diffs[:15]}


def main() -> None:
    global TESTS, SOL, BUILD
    TESTS, SOL, BUILD = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    m = json.loads((BUILD / "manifest.json").read_text())
    ids = [i["id"] for i in m["samples"] + m["hidden"]]
    with Pool(workers) as pool:
        results = pool.map(_one, ids)
    (BUILD / "reference.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"reference right on {sum(r['ok'] for r in results)} of {len(results)}; slowest {max(r['seconds'] for r in results):.0f} s")


if __name__ == "__main__":
    main()

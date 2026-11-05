"""Runs inside the pack's generator image: draw every planned item and confirm drawing left its truth alone.

python3 -I render_main.py PACK_DIR BUILD_DIR [WORKERS]
"""
from __future__ import annotations

import json
import random
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, "/tf/src")
from taskfactory.builder.items import item_size  # noqa: E402
from taskfactory.builder.pack import load_domain  # noqa: E402

PACK = BUILD = None


def _one(entry: dict) -> dict:
    pack = load_domain(PACK)
    seed = json.loads((BUILD / "manifest.json").read_text())["seed"]
    rng = random.Random(f"{seed}-{entry['id']}")
    item = pack.module.build(entry["id"], entry["house"], entry["route"], entry["units"], frozenset(entry["features"]), rng)
    path = BUILD / pack.ext / f"{entry['id']}.{pack.ext}"
    try:
        note = pack.module.render(item, path, rng)
    except Exception as e:  # reported, not raised: the gate decides
        return {"id": entry["id"], "error": f"{type(e).__name__}: {e}"}
    want = json.loads((BUILD / "truth" / f"{entry['id']}.json").read_text())
    got = json.loads(json.dumps(pack.module.truth(item), ensure_ascii=False))
    return {"id": entry["id"], "note": note, "truth_unchanged": got == want, "bytes": item_size(path)}


def main() -> None:
    global PACK, BUILD
    PACK, BUILD = Path(sys.argv[1]), Path(sys.argv[2])
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    (BUILD / load_domain(PACK).ext).mkdir(exist_ok=True)
    m = json.loads((BUILD / "manifest.json").read_text())
    with Pool(workers) as pool:
        results = pool.map(_one, m["samples"] + m["hidden"])
    (BUILD / "render.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    bad = [r for r in results if r.get("error") or not r.get("truth_unchanged")]
    print(f"rendered {len(results) - len(bad)} of {len(results)}")


if __name__ == "__main__":
    main()

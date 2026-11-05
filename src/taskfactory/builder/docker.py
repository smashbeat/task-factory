"""The stages that run inside the pack's images: drawing the documents and running the reference."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .items import copy_item
from .pack import Domain

SRC =Path(__file__).resolve().parents[2]


def image(pack: Domain, key: str) -> str:
    """The pack's image for `key`, built from the pack the first time it is needed."""
    tag = f"tf-{pack.name}-{key}"
    have = subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0
    if not have:
        ctx = pack.root / pack.extra.get("images", {}).get(key, f"{key}-env")
        subprocess.run(["docker", "build", "-q", "-t", tag, str(ctx)], check=True)
    return tag


def _run(img: str, mounts: list[tuple[Path, str, bool]], argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    cmd = ["docker", "run", "--rm"]
    for host, inside, ro in mounts:
        cmd += ["-v", f"{Path(host).resolve()}:{inside}" + (":ro" if ro else "")]
    return subprocess.run(cmd + [img] + argv, capture_output=True, text=True, timeout=timeout)


def render(pack: Domain, build: Path, workers: int = 6) -> subprocess.CompletedProcess:
    """Draw every item with the pack's own (trusted) renderer. Raises when the container fails."""
    p = _run(
        image(pack, "gen"),
        [(SRC, "/tf/src", True), (pack.root, "/pack", True), (build, "/build", False)],
        ["python3", "-I", "/tf/src/taskfactory/builder/render_main.py", "/pack", "/build", str(workers)],
        timeout=3600,
    )
    if p.returncode != 0:
        raise RuntimeError(f"render failed: {p.stderr[-800:]}")
    return p


def reference(pack: Domain, build: Path, solution: Path | None = None, workers: int = 6) -> list[dict]:
    """Run a solution on every item with only its inputs mounted, then score it here against the truth.

    The container sees the PDFs and specs read-only and has no network; answers stay on the host.
    Writes build/reference.json and returns it.
    """
    import importlib.util
    import json
    import shutil
    import tempfile

    build = Path(build)
    solution = Path(solution or pack.root / "task" / "solution" / "intake.py")
    with tempfile.TemporaryDirectory(prefix="tf-ref-") as td:
        inp, out, sol = Path(td) / "in", Path(td) / "out", Path(td) / "sol"
        inp.mkdir(), out.mkdir(), sol.mkdir()
        out.chmod(0o777)
        shutil.copy(solution, sol / "intake.py")
        for item in (build / pack.ext).glob(f"*.{pack.ext}"):
            copy_item(item, inp / item.name)
            shutil.copy(build / "specs" / f"{item.stem}.json", inp / f"{item.stem}.spec.json")
        cmd = ["docker", "run", "--rm", "--network", "none",
               "-v", f"{SRC}:/tf/src:ro", "-v", f"{sol}:/sol:ro", "-v", f"{inp}:/in:ro", "-v", f"{out}:/out",
               image(pack, "ref"), "python3", "-I", "/tf/src/taskfactory/builder/reference_main.py",
               "/sol/intake.py", "/in", "/out", str(workers), pack.ext, str(pack.seconds)]
        subprocess.run(cmd, capture_output=True, text=True, timeout=7200, check=True)
        spec = importlib.util.spec_from_file_location("tf_compare", pack.root / "task" / "tests" / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        results = []
        for r in json.loads((out / "runs.json").read_text()):
            i = r["id"]
            got = out / f"{i}.json"
            if r["returncode"] != 0 or not got.exists():
                diffs = [f"exit {r['returncode']}: {r['stderr']}"]
            else:
                diffs = compare.compare_files(got, build / "truth" / f"{i}.json")
            entry = {"id": i, "ok": not diffs, "seconds": r["seconds"], "diffs": diffs[:15]}
            if "seconds_parallel" in r:
                entry["seconds_parallel"] = r["seconds_parallel"]
            results.append(entry)
    (build / "reference.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    return results

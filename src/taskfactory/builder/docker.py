"""The stages that run inside the pack's images: drawing the documents and running the reference."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .pack import Domain

SRC = Path(__file__).resolve().parents[2]


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
    return _run(
        image(pack, "gen"),
        [(SRC, "/tf/src", True), (pack.root, "/pack", True), (build, "/build", False)],
        ["python3", "-I", "/tf/src/taskfactory/builder/render_main.py", "/pack", "/build", str(workers)],
        timeout=3600,
    )


def reference(pack: Domain, build: Path, workers: int = 6) -> subprocess.CompletedProcess:
    return _run(
        image(pack, "ref"),
        [(SRC, "/tf/src", True), (pack.root / "task", "/task", True), (build, "/build", False)],
        ["python3", "-I", "/tf/src/taskfactory/builder/reference_main.py", "/task/tests", "/task/solution/intake.py", "/build", str(workers)],
        timeout=7200,
    )

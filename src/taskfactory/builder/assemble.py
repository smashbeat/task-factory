"""Write the Harbor task directory from a rendered build and the pack's task template.

Samples go to environment/samples with their expected output; hidden items and their truth go to tests/.
A fresh canary GUID replaces the template's in every file that carries one.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from .pack import Domain

CANARY = re.compile(r"harbor-canary GUID [0-9a-f-]{36}")


def assemble(pack: Domain, build: Path, task: Path, name: str) -> Path:
    build, task = Path(build), Path(task)
    if task.exists():
        shutil.rmtree(task)
    shutil.copytree(pack.root / "task", task)
    m = json.loads((build / "manifest.json").read_text())
    samples = task / "environment" / "samples"
    hidden, truth = task / "tests" / "hidden", task / "tests" / "truth"
    for d in (samples, hidden, truth):
        d.mkdir(parents=True, exist_ok=True)
    ext = pack.ext
    for i in m["samples"]:
        shutil.copy(build / ext / f"{i['id']}.{ext}", samples / f"{i['id']}.{ext}")
        shutil.copy(build / "specs" / f"{i['id']}.json", samples / f"{i['id']}.spec.json")
        shutil.copy(build / "truth" / f"{i['id']}.json", samples / f"{i['id']}.expected.json")
    for i in m["hidden"]:
        shutil.copy(build / ext / f"{i['id']}.{ext}", hidden / f"{i['id']}.{ext}")
        shutil.copy(build / "specs" / f"{i['id']}.json", hidden / f"{i['id']}.spec.json")
        shutil.copy(build / "truth" / f"{i['id']}.json", truth / f"{i['id']}.truth.json")
    shutil.copy(build / "policy.md", task / "environment" / "policy.md")
    shutil.copy(build / "instruction.md", task / "instruction.md")
    guid = f"harbor-canary GUID {uuid.uuid4()}"
    for f in task.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".toml", ".sh", ".py", "") or f.name == "Dockerfile":
            try:
                text = f.read_text()
            except UnicodeDecodeError:
                continue
            new = CANARY.sub(guid, text)
            if f.name == "task.toml":
                new = re.sub(r'name = "terminal-bench/[^"]+"', f'name = "terminal-bench/{name}"', new)
            if new != text:
                f.write_text(new)
    return task

"""An item is what the renderer writes and the tool reads: one file (`ID.pdf`) or one folder (`ID.pkg/`)."""
from __future__ import annotations

import shutil
from pathlib import Path


def copy_item(src: Path, dst: Path) -> None:
    """Copy a file or a folder tree to `dst`, replacing whatever is there."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy(src, dst)


def item_size(path: Path) -> int:
    """Bytes of a file, or of every file under a folder."""
    path = Path(path)
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return path.stat().st_size

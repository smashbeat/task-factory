"""Items may be files or folders; a pack sets its own time limit and scan resolution."""
from pathlib import Path

from taskfactory.builder.items import copy_item, item_size
from taskfactory.builder.pack import load_domain

COA = Path(__file__).parent.parent / "packs" / "coa"


def test_copy_item_copies_a_file(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"%PDF-1.4 x")
    copy_item(src, tmp_path / "out" / "b.pdf")
    assert (tmp_path / "out" / "b.pdf").read_bytes() == b"%PDF-1.4 x"
    assert item_size(src) == 10


def test_copy_item_copies_a_folder_tree(tmp_path):
    src = tmp_path / "h01.pkg"
    (src / "mail").mkdir(parents=True)
    (src / "batch.xlsx").write_bytes(b"xlsx" * 3)
    (src / "mail" / "coa.eml").write_bytes(b"eml")
    copy_item(src, tmp_path / "out" / "h01.pkg")
    assert (tmp_path / "out" / "h01.pkg" / "batch.xlsx").read_bytes() == b"xlsx" * 3
    assert (tmp_path / "out" / "h01.pkg" / "mail" / "coa.eml").read_bytes() == b"eml"
    assert item_size(src) == 15
    copy_item(src, tmp_path / "out" / "h01.pkg")  # copying again replaces, never nests


def test_pack_defaults_keep_the_old_limits():
    d = load_domain(COA)
    assert d.seconds == 120 and d.scan_dpi == 300


def test_pack_can_set_its_own_limits(tmp_path):
    (tmp_path / "pack.toml").write_text(
        '[pack]\nname = "x"\nstyles = ["a"]\nroutes = ["digital"]\nseconds = 300\nscan_dpi = 200\next = "pkg"\n'
    )
    (tmp_path / "pack.py").write_text("def valid(*a):\n    return True\n")
    d = load_domain(tmp_path)
    assert d.seconds == 300 and d.scan_dpi == 200 and d.ext == "pkg"

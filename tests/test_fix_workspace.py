"""The fix agent's workspace: it starts from the latest candidate and can see what it must not break."""
import json
from pathlib import Path

from taskfactory.builder.agent import make_workspace
from taskfactory.builder.pack import load_domain

ROOT = Path(__file__).parent.parent


def _build(tmp_path):
    b = tmp_path / "build"
    for d in ("pdf", "specs", "truth"):
        (b / d).mkdir(parents=True)
    for i in ("h01", "h02"):
        (b / "pdf" / f"{i}.pdf").write_bytes(b"%PDF")
        (b / "specs" / f"{i}.json").write_text("{}")
        (b / "truth" / f"{i}.json").write_text("{}")
    (b / "policy.md").write_text("policy")
    (b / "reference.json").write_text(json.dumps([{"id": "h01", "ok": False, "diffs": ["x"]},
                                                  {"id": "h02", "ok": True, "diffs": []}]))
    return b


def test_workspace_starts_from_the_given_candidate(tmp_path):
    start = tmp_path / "candidate-0.py"
    start.write_text("# candidate 0\n")
    ws, failing = make_workspace(load_domain(ROOT / "packs" / "coa"), _build(tmp_path), 1, start)
    assert (ws / "intake.py").read_text() == "# candidate 0\n"
    assert failing == ["h01"]


def test_workspace_starts_from_the_pack_reference_by_default(tmp_path):
    pack = load_domain(ROOT / "packs" / "coa")
    ws, _ = make_workspace(pack, _build(tmp_path), 0, None)
    assert (ws / "intake.py").read_text() == (pack.root / "task" / "solution" / "intake.py").read_text()


def test_workspace_holds_the_passing_items_as_a_regression_set(tmp_path):
    ws, _ = make_workspace(load_domain(ROOT / "packs" / "coa"), _build(tmp_path), 0, None)
    assert sorted(p.name for p in (ws / "passing").iterdir()) == ["h02.expected.json", "h02.pdf", "h02.spec.json"]
    assert not (ws / "failing" / "h02.pdf").exists()


def test_workspace_takes_several_seeds_and_keeps_their_ids_apart(tmp_path):
    a, b = _build(tmp_path / "a"), _build(tmp_path / "b")
    (a / "manifest.json").write_text(json.dumps({"seed": 1}))
    (b / "manifest.json").write_text(json.dumps({"seed": 1001}))
    ws, failing = make_workspace(load_domain(ROOT / "packs" / "coa"), [a, b], 0, None)
    assert failing == ["1-h01", "1001-h01"]
    assert sorted(p.name for p in (ws / "failing").glob("*.pdf")) == ["1-h01.pdf", "1001-h01.pdf"]

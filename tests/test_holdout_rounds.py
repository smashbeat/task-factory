"""The fix loop across holdout rounds, with Docker and the agent replaced by fakes."""
import json
import shutil
from pathlib import Path

from taskfactory.builder import agent, assemble, docker
from taskfactory.builder.build import build

ROOT = Path(__file__).parent.parent


def _ids(d):
    m = json.loads((d / "manifest.json").read_text())
    return [i["id"] for i in m["samples"] + m["hidden"]]


def test_a_failed_holdout_becomes_training_data_and_a_fresh_seed_decides(tmp_path, monkeypatch):
    pack = tmp_path / "coa"
    shutil.copytree(ROOT / "packs" / "coa", pack)
    # which solution passes where: the pack's reference passes nothing; candidate 1 passes seed 1 only;
    # candidate 2 passes seed 1 and both holdouts
    passes = {"intake.py": set(), "v1": {"out"}, "v2": {"out", "holdout-1001", "holdout-2001"}}
    seen = []

    def render(p, d, workers=6):
        (d / "render.json").write_text(json.dumps([{"id": i, "truth_unchanged": True} for i in _ids(d)]))

    def reference(p, d, solution=None):
        who = (solution or p.root / "task" / "solution" / "intake.py").read_text().strip() if solution else "intake.py"
        ok = d.name in passes[who]
        (d / "reference.json").write_text(json.dumps([{"id": i, "ok": ok, "diffs": [] if ok else ["x"], "seconds": 1}
                                                      for i in _ids(d)]))

    def fix(p, builds, image, attempt, model=None, start=None):
        seen.append([b.name for b in builds])
        f = tmp_path / f"fix-{len(seen)}.py"
        f.write_text("v1" if len(seen) == 1 else "v2")
        return {"error": False, "disputed": False, "dispute": None, "summary": "", "cost_usd": 0, "fixed_file": str(f)}

    monkeypatch.setattr(docker, "render", render)
    monkeypatch.setattr(docker, "reference", reference)
    monkeypatch.setattr(docker, "image", lambda p, k: "img")
    monkeypatch.setattr(agent, "fix_reference", fix)
    monkeypatch.setattr(assemble, "assemble", lambda *a: None)
    out = tmp_path / "out"
    out.mkdir()
    run = build(pack, 1, out / "out", docker=True, fix=True)
    assert seen == [["out"], ["out", "holdout-1001"]]
    assert run.verdict == "task assembled, ready for trials"
    assert (pack / "task" / "solution" / "intake.py").read_text() == "v2"


def test_holdout_rounds_stop_after_the_last_round(tmp_path, monkeypatch):
    pack = tmp_path / "coa"
    shutil.copytree(ROOT / "packs" / "coa", pack)
    ref = (pack / "task" / "solution" / "intake.py").read_text()

    monkeypatch.setattr(docker, "render", lambda p, d, workers=6: (d / "render.json").write_text(
        json.dumps([{"id": i, "truth_unchanged": True} for i in _ids(d)])))
    # every candidate passes whatever it was trained on and fails every fresh seed
    trained = set()

    def reference(p, d, solution=None):
        ok = solution is not None and d.name in trained
        (d / "reference.json").write_text(json.dumps([{"id": i, "ok": ok, "diffs": [] if ok else ["x"], "seconds": 1}
                                                      for i in _ids(d)]))

    def fix(p, builds, image, attempt, model=None, start=None):
        trained.update(b.name for b in builds)
        f = tmp_path / "fix.py"
        f.write_text("overfit")
        return {"error": False, "disputed": False, "dispute": None, "summary": "", "cost_usd": 0, "fixed_file": str(f)}

    monkeypatch.setattr(docker, "reference", reference)
    monkeypatch.setattr(docker, "image", lambda p, k: "img")
    monkeypatch.setattr(agent, "fix_reference", fix)
    run = build(pack, 1, tmp_path / "out", docker=True, fix=True)
    assert run.stopped_at == "holdout"
    assert trained == {"out", "holdout-1001", "holdout-2001"}
    assert (pack / "task" / "solution" / "intake.py").read_text() == ref


def test_a_build_can_start_from_an_earlier_candidate(tmp_path, monkeypatch):
    pack = tmp_path / "coa"
    shutil.copytree(ROOT / "packs" / "coa", pack)
    start = tmp_path / "earlier.py"
    start.write_text("earlier")
    used, fixes = [], []

    monkeypatch.setattr(docker, "render", lambda p, d, workers=6: (d / "render.json").write_text(
        json.dumps([{"id": i, "truth_unchanged": True} for i in _ids(d)])))

    def reference(p, d, solution=None):
        used.append(solution.read_text() if solution else "intake.py")
        ok = solution is not None and solution.read_text() == "earlier"
        (d / "reference.json").write_text(json.dumps([{"id": i, "ok": ok, "diffs": [] if ok else ["x"], "seconds": 1}
                                                      for i in _ids(d)]))

    def fix(p, builds, image, attempt, model=None, start=None):
        fixes.append(start)
        raise AssertionError("the earlier candidate passes, so no fix is needed")

    monkeypatch.setattr(docker, "reference", reference)
    monkeypatch.setattr(docker, "image", lambda p, k: "img")
    monkeypatch.setattr(agent, "fix_reference", fix)
    monkeypatch.setattr(assemble, "assemble", lambda *a: None)
    run = build(pack, 1, tmp_path / "out", docker=True, fix=True, start_from=start)
    assert used == ["earlier", "earlier"]          # training seed, then the holdout
    assert fixes == []
    assert run.verdict == "task assembled, ready for trials"
    assert (pack / "task" / "solution" / "intake.py").read_text() == "earlier"


def _near_miss(tmp_path, monkeypatch, wrong):
    """The pack's reference passes the training seed and gets `wrong` items of each fresh seed wrong."""
    pack = tmp_path / "coa"
    shutil.copytree(ROOT / "packs" / "coa", pack)
    monkeypatch.setattr(docker, "render", lambda p, d, workers=6: (d / "render.json").write_text(
        json.dumps([{"id": i, "truth_unchanged": True} for i in _ids(d)])))

    def reference(p, d, solution=None):
        ids = _ids(d)
        bad = set(ids[:wrong]) if d.name.startswith("holdout") else set()
        (d / "reference.json").write_text(json.dumps([{"id": i, "ok": i not in bad, "diffs": ["x"] if i in bad else [],
                                                       "seconds": 1} for i in ids]))

    def fix(p, builds, image, attempt, model=None, start=None):
        f = tmp_path / "fix.py"
        f.write_text("fixed")
        return {"error": False, "disputed": False, "dispute": None, "summary": "", "cost_usd": 0, "fixed_file": str(f)}

    monkeypatch.setattr(docker, "reference", reference)
    monkeypatch.setattr(docker, "image", lambda p, k: "img")
    monkeypatch.setattr(agent, "fix_reference", fix)
    monkeypatch.setattr(assemble, "assemble", lambda *a: None)
    start = tmp_path / "earlier.py"
    start.write_text("earlier")
    return build(pack, 1, tmp_path / "out", docker=True, fix=True, start_from=start)


def test_a_fresh_seed_passes_when_nine_in_ten_are_right(tmp_path, monkeypatch):
    run = _near_miss(tmp_path, monkeypatch, wrong=4)          # 37 of 41
    assert run.verdict == "task assembled, ready for trials"
    hold = [x for x in run.log if x["stage"] == "holdout"]
    assert hold[0]["status"] == "warn"
    assert any("37 of 41" in f["text"] for f in hold[0]["findings"])


def test_a_fresh_seed_fails_below_nine_in_ten(tmp_path, monkeypatch):
    run = _near_miss(tmp_path, monkeypatch, wrong=5)          # 36 of 41
    assert [x["status"] for x in run.log if x["stage"] == "holdout"][0] == "fail"
    assert run.verdict != "task assembled, ready for trials"

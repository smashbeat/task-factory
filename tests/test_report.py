from pathlib import Path

from taskfactory.attribution import load_profile
from taskfactory.cli import main
from taskfactory.evidence import load_pack
from taskfactory.pipeline import run
from taskfactory.report import render_html

PACK = Path(__file__).parent / "fixtures" / "coa-intake"


def test_report_shows_verdict_gates_and_the_attribution_matrix():
    out = run(load_pack(PACK), load_profile(PACK / "factory.toml"))
    html = render_html(out)
    assert "<title>" in html and "coa-intake" in html
    assert "ship with warnings" in html
    for gate in ("Quality", "Difficulty", "Fairness", "Cheat"):
        assert gate in html
    assert 'data-kind="rule"' in html and 'data-kind="reading"' in html
    assert "footnote" in html


def test_report_escapes_agent_text():
    pack = load_pack(PACK)
    t = pack.trial("JjKSvue")
    t.agent = "<script>x</script>"
    html = render_html(run(pack, load_profile(PACK / "factory.toml")))
    assert "<script>x</script>" not in html


def test_cli_writes_the_report_and_exits_zero_on_ship(tmp_path, capsys):
    target = tmp_path / "report.html"
    code = main(["check", str(PACK), "--html", str(target)])
    assert code == 0 and target.exists()
    assert "ship with warnings" in capsys.readouterr().out

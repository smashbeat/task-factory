"""One HTML page per run, built to be shown on a screen: the verdict, the gates, and why each failure happened."""
from __future__ import annotations

import datetime as dt
from html import escape

from .gates import GATES
from .pipeline import Run

STAGE = {"quality": "Gate 3", "difficulty": "Gate 5", "fairness": "Gate 6", "cheat": "Gate 7"}
COST = {"quality": "minutes", "difficulty": "hours of agent time", "fairness": "seconds, no model calls", "cheat": "1 to 2 hours"}
NOT_YET = [
    ("Gate 1, spec", "trace every test assertion to a sentence of the instruction; ask three model families the edge cases from the instruction alone"),
    ("Gate 2, generator", "fingerprint audit: can a model tell the generator's hidden choices from fonts, producer strings or coordinates?"),
    ("Gate 3, verifier mutation", "remove one rule at a time from the reference; the verifier must fail each mutant"),
    ("Gate 4, cheap screen", "one mid-tier agent with a 20-minute cap before any frontier trial"),
    ("Gate 5, checkpoints", "run the hidden verifier on snapshots of a live trial, out of band, and stop a trial that is already passing"),
    ("Gate 6, seed replay and judge", "rerun each agent's finished program on fresh seeds; send unexplained failures to a calibrated judge"),
]

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#16181d;--muted:#5d636f;--line:#e3e4e8;--pass:#1f7a4d;--pass-bg:#e6f4ec;
--warn:#9a6300;--warn-bg:#fdf3dc;--fail:#b3261e;--fail-bg:#fbe7e5;--rule:#3b5bdb;--rule-bg:#e7ecfd;--read:#6b7280;--read-bg:#eef0f3;
--unx:#b3261e;--unx-bg:#fbe7e5;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111317;--card:#1a1d23;--ink:#e8e9ec;--muted:#9aa0ab;--line:#2b2f37;
--pass:#5fd39a;--pass-bg:#173326;--warn:#f0c060;--warn-bg:#3a2e12;--fail:#ff8a80;--fail-bg:#3b1a18;--rule:#8ea6ff;--rule-bg:#1e2747;
--read:#b4b9c2;--read-bg:#2a2e36;--unx:#ff8a80;--unx-bg:#3b1a18;--accent:#8ea6ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"Inter","Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 16px 64px}h1{font-size:28px;margin:0}h2{font-size:18px;margin:36px 0 12px}
.sub{color:var(--muted);margin-top:4px}.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-weight:600;font-size:13px}
.pass{color:var(--pass);background:var(--pass-bg)}.warn{color:var(--warn);background:var(--warn-bg)}.fail{color:var(--fail);background:var(--fail-bg)}
.skip{color:var(--muted);background:var(--read-bg)}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.verdict{font-size:20px;padding:8px 16px}
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:24px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.chip b{display:block}.chip small{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:12px 0}
.card h3{margin:0 0 8px;font-size:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
ul.f{list-style:none;padding:0;margin:0}ul.f li{padding:5px 0 5px 22px;position:relative;border-top:1px solid var(--line)}
ul.f li:first-child{border-top:0}ul.f li:before{position:absolute;left:0;top:5px;font-weight:700}
li.info:before{content:"✓";color:var(--pass)}li.warn:before{content:"!";color:var(--warn)}li.fail:before{content:"✕";color:var(--fail)}
.back{margin-top:10px;font-weight:600;color:var(--fail)}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:14px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
td.c{text-align:center;white-space:nowrap}
.cell{display:inline-block;min-width:54px;padding:2px 6px;border-radius:6px;font-weight:600}
[data-kind=rule]{color:var(--rule);background:var(--rule-bg)}[data-kind=reading]{color:var(--read);background:var(--read-bg)}
[data-kind=unexplained]{color:var(--unx);background:var(--unx-bg)}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 12px;color:var(--muted);font-size:13px}
code{font:12px ui-monospace,Menlo,monospace}.muted{color:var(--muted)}
.feat{color:var(--muted);font-size:12px}
"""


def _pill(status: str) -> str:
    return f'<span class="pill {status}">{escape(status)}</span>'


def _cell(a) -> str:
    if a is None:
        return '<span class="muted">·</span>'
    label = "rule " + ",".join(map(str, a.rules)) if a.kind == "rule" else a.kind
    tip = escape(a.says or "; ".join(f"{d.field}: {d.got!r} vs {d.want!r}" for d in a.residue[:3]))
    return f'<span class="cell" data-kind="{a.kind}" title="{tip}">{escape(label)}</span>'


def render_html(r: Run) -> str:
    gates = {g.gate: g for g in r.gates}
    verdict_cls = {"ship": "pass", "ship with warnings": "warn", "send back": "fail"}[r.verdict]
    back = f'<div class="back">Send back to: {escape(r.send_back)}</div>' if r.send_back else ""
    strip = []
    for g in GATES:
        name = g.__name__
        res = gates.get(name)
        status = res.status if res else "skip"
        strip.append(f'<div class="chip"><small>{STAGE[name]} · {COST[name]}</small><b>{name.title()}</b>{_pill(status if res else "skipped")}</div>')
    cards = []
    for g in r.gates:
        lis = "".join(f'<li class="{f.level}">{escape(f.text)}</li>' for f in g.findings)
        sb = f'<div class="back">Send back to: {escape(g.send_back)}</div>' if g.send_back else ""
        cards.append(f'<div class="card"><h3>{escape(g.title)} {_pill(g.status)}</h3><ul class="f">{lis}</ul>{sb}</div>')
    matrix = ""
    fair = gates.get("fairness")
    if fair and fair.attributions:
        trials = list(fair.attributions)
        by = {t: {a.item: a for a in atts} for t, atts in fair.attributions.items()}
        items = sorted({i for m in by.values() for i in m})
        head = "".join(f"<th>{escape(t.split('__')[-1])}<div class='feat'>{escape(r.agents.get(t, ''))}</div></th>" for t in trials)
        rows = "".join(
            f"<tr><th>{escape(i)}</th>" + "".join(f'<td class="c">{_cell(by[t].get(i))}</td>' for t in trials) + "</tr>"
            for i in items
        )
        rules: dict[str, dict] = {}
        for t in trials:
            for a in fair.attributions[t]:
                if a.kind == "rule":
                    e = rules.setdefault(a.item, {"trials": [], "says": {}, "rules": set(), "features": {}})
                    e["trials"].append(t.split("__")[-1])
                    e["says"][a.says] = None
                    e["rules"].update(a.rules)
                    e["features"].update(dict.fromkeys(a.features))
        rt = "".join(
            f"<tr><td><b>{escape(i)}</b></td><td>{escape('; or '.join(e['says']))}<div class='feat'>generator features: {escape(', '.join(e['features']))}</div></td>"
            f"<td>{escape(', '.join(map(str, sorted(e['rules']))))}</td><td>{escape(', '.join(e['trials']))}</td></tr>"
            for i, e in sorted(rules.items())
        )
        matrix = f"""
<h2>Why each failure happened</h2>
<div class="legend"><span><span class="cell" data-kind="rule">rule</span> broke a written rule while reading the page right</span>
<span><span class="cell" data-kind="reading">reading</span> misread what prints</span>
<span><span class="cell" data-kind="unexplained">unexplained</span> goes to the judge</span></div>
<div class="scroll"><table><tr><th>Item</th>{head}</tr>{rows}</table></div>
<h2>Rule-decided failures</h2>
<div class="scroll"><table><tr><th>Item</th><th>What the agent did</th><th>Rules</th><th>Trials</th></tr>{rt}</table></div>"""
    todo = "".join(f"<tr><td><b>{escape(a)}</b></td><td>{escape(b)}</td></tr>" for a, b in NOT_YET)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Task Factory: {escape(r.task)}</title><style>{CSS}</style></head><body><main>
<div class="head"><div><h1>{escape(r.task)}</h1><div class="sub">Gates run on the task's evidence pack · {now}</div></div>
<div><span class="pill verdict {verdict_cls}">{escape(r.verdict)}</span>{back}</div></div>
<div class="strip">{''.join(strip)}</div>
{''.join(cards)}
{matrix}
<h2>Not automated yet</h2>
<div class="scroll"><table>{todo}</table></div>
</main></body></html>"""

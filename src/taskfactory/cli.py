"""taskfactory check <pack> [--profile factory.toml] [--html report.html] [--keep-going]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .attribution import load_profile
from .evidence import load_pack
from .pipeline import run
from .report import render_html

MARK = {"info": " ", "warn": "!", "fail": "x"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="taskfactory", description="Check a task's quality, difficulty and fairness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="run the gates on an evidence pack")
    c.add_argument("pack", type=Path)
    c.add_argument("--profile", type=Path, help="defaults to <pack>/factory.toml")
    c.add_argument("--html", type=Path, help="write the report page here")
    c.add_argument("--keep-going", action="store_true", help="run every gate even after one fails")
    a = ap.parse_args(argv)

    profile = load_profile(a.profile or a.pack / "factory.toml")
    out = run(load_pack(a.pack, profile.manifest), profile, keep_going=a.keep_going)
    for g in out.gates:
        print(f"[{g.status:4}] {g.gate}")
        for f in g.findings:
            print(f"   {MARK[f.level]} {f.text}")
    for s in out.skipped:
        print(f"[skip] {s}")
    print(f"\n{out.verdict}" + (f": send back to {out.send_back}" if out.send_back else ""))
    if a.html:
        a.html.write_text(render_html(out))
        print(f"report: {a.html}")
    return 1 if out.verdict == "send back" else 0


if __name__ == "__main__":
    sys.exit(main())

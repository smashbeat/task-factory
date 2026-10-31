"""Run the gates in cost order and stop at the first failure, unless asked to keep going."""
from __future__ import annotations

from dataclasses import dataclass, field

from .attribution import Profile
from .evidence import Pack
from .gates import GATES, GateResult


@dataclass
class Run:
    task: str
    gates: list[GateResult]
    skipped: list[str] = field(default_factory=list)
    agents: dict[str, str] = field(default_factory=dict)

    @property
    def send_back(self) -> str | None:
        return next((g.send_back for g in self.gates if g.status == "fail"), None)

    @property
    def verdict(self) -> str:
        statuses = {g.status for g in self.gates}
        if "fail" in statuses:
            return "send back"
        return "ship with warnings" if "warn" in statuses else "ship"


def run(pack: Pack, profile: Profile, keep_going: bool = False) -> Run:
    out = Run(profile.name, [], agents={t.name: t.agent or "" for t in pack.trials})
    for i, gate in enumerate(GATES):
        r = gate(pack, profile)
        out.gates.append(r)
        if r.status == "fail" and not keep_going:
            out.skipped = [g.__name__ for g in GATES[i + 1 :]]
            break
    return out

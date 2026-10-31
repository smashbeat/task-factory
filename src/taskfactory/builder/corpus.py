"""Truth for every item, and the mutant answers: what an agent that ignored one rule would write."""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from .pack import Domain
from .plan import Plan


@dataclass
class Corpus:
    seed: int
    truth: dict[str, dict]
    specs: dict[str, dict]
    mutants: dict[str, dict[int, dict]]  # item -> rule -> answer, only where the answer differs

    def digest(self) -> str:
        blob = json.dumps({"t": self.truth, "s": self.specs, "m": {k: {str(r): v for r, v in m.items()} for k, m in self.mutants.items()}}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


def make_corpus(pack: Domain, plan: Plan, seed: int) -> Corpus:
    mutant_rules = [r.id for r in pack.rules if r.mutant]
    truth, specs, mutants = {}, {}, {}
    for it in plan.samples + plan.hidden:
        model = pack.module.build(it.id, it.style, it.route, it.units, it.features, random.Random(f"{seed}-{it.id}"))
        t = pack.module.truth(model)
        truth[it.id] = t
        specs[it.id] = pack.module.spec(model)
        m = {}
        for r in mutant_rules:
            a = pack.module.truth(model, frozenset({r}))
            if a != t:
                m[r] = a
        mutants[it.id] = m
    return Corpus(seed, truth, specs, mutants)

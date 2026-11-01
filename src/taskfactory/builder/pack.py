"""A domain pack: rules and features as data (pack.toml) plus an adapter module that builds and answers items."""
from __future__ import annotations

import importlib.util
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class Rule:
    id: int
    title: str
    text: str
    mutant: bool


@dataclass(frozen=True)
class Feature:
    name: str
    rules: tuple[int, ...]
    says: str
    routes: tuple[str, ...]
    units: int
    requires_any: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    kind: str = "rule"


@dataclass
class Domain:
    root: Path
    name: str
    item: str
    unit: str
    module: ModuleType
    rules: tuple[Rule, ...]
    features: tuple[Feature, ...]
    styles: tuple[str, ...]
    routes: tuple[str, ...]
    reading_routes: frozenset[str]
    route_rules: dict[str, tuple[int, ...]]
    samples_max: int
    hidden: int
    units_max: int
    hidden_features: tuple[int, int] = (1, 1)
    hidden_several: float = 0.0
    hidden_reading: float = 0.0
    extra: dict = field(default_factory=dict)

    def rule(self, rid: int) -> Rule:
        return next(r for r in self.rules if r.id == rid)

    def feature(self, name: str) -> Feature:
        return next(f for f in self.features if f.name == name)


def _module(root: Path, name: str) -> ModuleType:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(f"taskfactory_pack_{root.name}_{name}", root / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_domain(root: Path) -> Domain:
    root = Path(root)
    d = tomllib.loads((root / "pack.toml").read_text())
    p = d["pack"]
    routes = tuple(p["routes"])
    units_max = p.get("units_max", 3)
    rules = tuple(Rule(r["id"], r["title"], r["text"], r.get("mutant", False)) for r in d.get("rule", []))
    feats = tuple(
        Feature(
            name=f["name"],
            rules=tuple(f.get("rules", ())),
            says=f.get("says", ""),
            routes=tuple(f.get("routes", routes)),
            units=f.get("units", units_max),
            requires_any=tuple(f.get("requires_any", ())),
            excludes=tuple(f.get("excludes", ())),
            kind=f.get("kind", "rule"),
        )
        for f in d.get("feature", [])
    )
    return Domain(
        root=root,
        name=p["name"],
        item=p.get("item", "item"),
        unit=p.get("unit", "unit"),
        module=_module(root, p.get("module", "pack")),
        rules=rules,
        features=feats,
        styles=tuple(p["styles"]),
        routes=routes,
        reading_routes=frozenset(p.get("reading_routes", ())),
        route_rules={k: tuple(v) for k, v in p.get("route_rules", {}).items()},
        samples_max=p.get("samples_max", 12),
        hidden=p.get("hidden", 30),
        units_max=units_max,
        hidden_features=tuple(p.get("hidden_features", (1, len(feats)))),
        hidden_several=p.get("hidden_several", 0.0),
        hidden_reading=p.get("hidden_reading", 0.0),
        extra={k: v for k, v in d.items() if k not in ("pack", "rule", "feature")},
    )

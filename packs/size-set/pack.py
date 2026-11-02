"""size-set pack adapter: what the domain-free builder calls."""
from __future__ import annotations

import model

FORM_ROUTES = {"form", "form_mismatch"}
COLUMN_FEATURES = {"spec_stale": "spec", "diff_wrong": "diff", "status_lies": "status"}


def valid(style: str, route: str, units: int, features: frozenset[str]) -> bool:
    """Combinations the renderer cannot draw. A form holds one size; a column lie needs a template that prints
    that column."""
    if route in FORM_ROUTES and units > 1:
        return False
    prints = set(model.HOUSES[style]["prints"])
    for name, col in COLUMN_FEATURES.items():
        if name in features and col not in prints:
            return False
    return units >= model.min_units(set(features))


def build(item_id: str, style: str, route: str, units: int, features: frozenset[str], rng):
    c = model.Report(item_id, style, rng, units, set(features), route)
    model.apply_features(c)
    return c


def truth(item, off: frozenset[int] = frozenset()) -> dict:
    return item.truth(off)


def spec(item) -> dict:
    return item.spec


def render(item, path, rng) -> str:
    import render as _render  # needs the generator image's fonts and tools

    return _render.render_item(item, str(path), rng)

"""packet-log pack adapter: what the domain-free builder calls."""
from __future__ import annotations

import model


def valid(style: str, route: str, units: int, features: frozenset[str]) -> bool:
    """A capture must hold enough frames for its features."""
    return units >= model.min_units(set(features))


def build(item_id: str, style: str, route: str, units: int, features: frozenset[str], rng):
    return model.Capture(item_id, style, rng, units, set(features), route)


def truth(item, off: frozenset[int] = frozenset()) -> dict:
    return item.truth(off)


def spec(item) -> dict:
    return item.spec()


def render(item, path, rng) -> str:
    import render as _render  # needs the generator image's sox and direwolf

    return _render.render_item(item, str(path), rng)

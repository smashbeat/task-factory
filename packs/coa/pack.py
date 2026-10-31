"""coa pack adapter: what the domain-free builder calls."""
from __future__ import annotations

import model

FORM_ROUTES = {"form", "form_mismatch"}


def valid(style: str, route: str, units: int, features: frozenset[str]) -> bool:
    """Combinations the renderer cannot draw. A form holds one lot."""
    return not (route in FORM_ROUTES and units > 1)


def build(item_id: str, style: str, route: str, units: int, features: frozenset[str], rng):
    c = model.Cert(item_id, style, rng, units, set(features), route)
    c.revision_style = "page" if "rev_page" in features else "block"
    model.apply_features(c)
    return c


def truth(item, off: frozenset[int] = frozenset()) -> dict:
    return item.truth(off)


def spec(item) -> dict:
    return item.spec

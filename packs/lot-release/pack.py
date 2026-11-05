"""lot-release pack adapter: what the domain-free builder calls."""
from __future__ import annotations

import model

MAX_PAGES = 12
NON_SCAN = {"digital", "distilled", "outlined", "form", "form_mismatch"}


def valid(style: str, route: str, units: int, features: frozenset[str]) -> bool:
    """Compositions the pack cannot draw. A member route needs a package route it differs from; a certificate as
    a form holds one lot; the PDF pages of the package stay under the cap."""
    if units < model.min_units(set(features)):
        return False
    if features & {"member_scan", "member_outlined"} and route not in NON_SCAN:
        return False
    if "member_outlined" in features and route == "outlined":
        return False
    if route in model.FORM_ROUTES and "coa_two_lots" in features:
        return False
    if _pages(units, set(features)) > MAX_PAGES:
        return False
    return True


def _pages(units: int, features: set) -> int:
    """An upper estimate of the package's PDF pages: label, report, one page per certificate plus the extras."""
    certs = units + ("two_lots_dispensed" in features) + ("extra_certificate" in features) \
        + ("eml_reply_supersedes" in features) + ("void_document" in features) - ("coa_missing" in features)
    return 2 + certs + ("coa_two_lots" in features)


def build(item_id: str, style: str, route: str, units: int, features: frozenset[str], rng):
    p = model.Package(item_id, style, rng, units, set(features), route)
    model.apply_features(p)
    return p


def truth(item, off: frozenset[int] = frozenset()) -> dict:
    return item.truth(off)


def spec(item) -> dict:
    return item.spec


def render(item, path, rng) -> str:
    import render as _render  # needs the generator image's fonts and tools

    return _render.render_item(item, str(path), rng)

from __future__ import annotations

import hashlib

CRAYON_COLORS = [
    "cornflowerblue",
    "lightcoral",
    "gold",
    "mediumseagreen",
    "orchid",
    "sandybrown",
    "plum",
    "turquoise",
    "khaki",
    "salmon",
]


def color_for(name: str) -> str:
    """Return a pseudo-random but stable color for a given name.

    Picks from CRAYON_COLORS using a SHA256 hash for determinism so the same
    node type is colored consistently across exports.
    """
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()
    idx = int(h, 16) % len(CRAYON_COLORS)
    return CRAYON_COLORS[idx]


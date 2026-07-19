"""Pick section integrator depending on triangle availability."""

from __future__ import annotations

from typing import Literal


def section_integrator() -> Literal["fiber", "marin"]:
    """
    Prefer fiber (as in HPDesignBench). Uses native ``triangle`` when
    installed, otherwise the pure-Python ``triangle_compat`` shim.
    Fall back to marin only if neither provides ``triangulate``.
    """
    try:
        import triangle

        if getattr(triangle, "__hp_stub__", False):
            return "marin"
        if not callable(getattr(triangle, "triangulate", None)):
            return "marin"
        return "fiber"
    except Exception:
        return "marin"

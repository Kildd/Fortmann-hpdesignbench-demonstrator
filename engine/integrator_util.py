"""Pick section integrator depending on triangle availability."""

from __future__ import annotations

from typing import Literal


def section_integrator() -> Literal["fiber", "marin"]:
    """
    Prefer fiber (as in HPDesignBench). Fall back to marin when the
    ``triangle`` package is missing or only a Pyodide stub is present.
    """
    try:
        import triangle

        if getattr(triangle, "__hp_stub__", False):
            return "marin"
        return "fiber"
    except Exception:
        return "marin"

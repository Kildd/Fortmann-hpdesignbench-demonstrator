"""Feasibility assessment for demonstrator trial results."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

FEAS_TOL = 1e-9


def expected_constraint_names(constraints: Mapping[str, Any]) -> list[str]:
    """Active design proofs for the current problem (excludes modeling Z*).

    Z1–Z3 remain in the analysis / penalty stack but are not treated as
    user-facing Nachweise for ``bestFeasible`` in this demonstrator.
    """
    names: list[str] = []
    for name, meta in constraints.items():
        if not meta.get("active", True):
            continue
        if str(name).startswith("Z"):
            continue
        names.append(str(name))
    return names


def assess_feasibility(
    utilizations: Mapping[str, Any] | None,
    *,
    error: str | None,
    expected: Iterable[str],
) -> dict[str, bool]:
    """Assess model validity and design feasibility for expected proofs.

    ``model_valid``
        Every expected key is present with a finite numeric value.
    ``design_feasible``
        Every present finite expected utilization is ≤ 1 + FEAS_TOL.
        Missing / non-finite values do not flip this flag (they fail
        ``model_valid`` instead).
    ``is_feasible``
        No analysis error, model valid, and design feasible.
    """
    expected_names = list(expected)
    if error is not None:
        return {
            "model_valid": False,
            "design_feasible": False,
            "is_feasible": False,
        }
    if not expected_names:
        return {
            "model_valid": False,
            "design_feasible": False,
            "is_feasible": False,
        }

    util = utilizations or {}
    model_valid = True
    design_feasible = True

    for name in expected_names:
        if name not in util:
            model_valid = False
            continue
        v = util[name]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            model_valid = False
            continue
        if not math.isfinite(float(v)):
            model_valid = False
            continue
        if float(v) > 1.0 + FEAS_TOL:
            design_feasible = False

    is_feasible = model_valid and design_feasible
    return {
        "model_valid": model_valid,
        "design_feasible": design_feasible,
        "is_feasible": is_feasible,
    }


def may_update_best_feasible(
    *,
    is_feasible: bool,
    y: float,
    best_feasible: Mapping[str, Any] | None,
) -> bool:
    """True if this trial should become the new bestFeasible by finite y."""
    if not is_feasible:
        return False
    if not math.isfinite(y):
        return False
    if best_feasible is None:
        return True
    prev = best_feasible.get("y")
    if prev is None or not math.isfinite(float(prev)):
        return True
    return y < float(prev)

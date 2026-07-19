"""Unit tests for demonstrator feasibility assessment."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from feasibility import (  # noqa: E402
    FEAS_TOL,
    assess_feasibility,
    expected_constraint_names,
    may_update_best_feasible,
)

EXPECTED = [
    "A_bending_capacity",
    "B1a_deflection_by_wmax_capacity",
    "C1_concrete_cover_capacity",
]


def _ok_util(**overrides: float) -> dict[str, float]:
    base = {name: 0.5 for name in EXPECTED}
    base.update(overrides)
    return base


class FeasibilityTests(unittest.TestCase):
    def test_all_finite_and_le_one_is_feasible(self) -> None:
        result = assess_feasibility(_ok_util(), error=None, expected=EXPECTED)
        self.assertTrue(result["model_valid"])
        self.assertTrue(result["design_feasible"])
        self.assertTrue(result["is_feasible"])

    def test_value_exactly_one_plus_tol_is_feasible(self) -> None:
        result = assess_feasibility(
            _ok_util(A_bending_capacity=1.0 + FEAS_TOL),
            error=None,
            expected=EXPECTED,
        )
        self.assertTrue(result["is_feasible"])

    def test_value_above_one_plus_tol_is_infeasible(self) -> None:
        result = assess_feasibility(
            _ok_util(A_bending_capacity=1.0 + FEAS_TOL + 1e-12),
            error=None,
            expected=EXPECTED,
        )
        self.assertTrue(result["model_valid"])
        self.assertFalse(result["design_feasible"])
        self.assertFalse(result["is_feasible"])

    def test_missing_expected_constraint_is_infeasible(self) -> None:
        util = _ok_util()
        del util["C1_concrete_cover_capacity"]
        result = assess_feasibility(util, error=None, expected=EXPECTED)
        self.assertFalse(result["model_valid"])
        self.assertTrue(result["design_feasible"])
        self.assertFalse(result["is_feasible"])

    def test_nan_or_infinity_is_infeasible(self) -> None:
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(bad=bad):
                result = assess_feasibility(
                    _ok_util(A_bending_capacity=bad),
                    error=None,
                    expected=EXPECTED,
                )
                self.assertFalse(result["model_valid"])
                self.assertFalse(result["is_feasible"])

    def test_analysis_error_is_infeasible(self) -> None:
        result = assess_feasibility(
            _ok_util(),
            error="RuntimeError: boom",
            expected=EXPECTED,
        )
        self.assertFalse(result["model_valid"])
        self.assertFalse(result["design_feasible"])
        self.assertFalse(result["is_feasible"])

    def test_design_feasible_true_model_valid_false_is_not_feasible(self) -> None:
        util = _ok_util()
        del util["B1a_deflection_by_wmax_capacity"]
        result = assess_feasibility(util, error=None, expected=EXPECTED)
        self.assertTrue(result["design_feasible"])
        self.assertFalse(result["model_valid"])
        self.assertFalse(result["is_feasible"])

    def test_non_finite_y_never_updates_best_feasible(self) -> None:
        self.assertFalse(
            may_update_best_feasible(
                is_feasible=True,
                y=math.nan,
                best_feasible=None,
            )
        )
        self.assertFalse(
            may_update_best_feasible(
                is_feasible=True,
                y=math.inf,
                best_feasible=None,
            )
        )

    def test_best_feasible_chosen_by_smallest_finite_y(self) -> None:
        self.assertTrue(
            may_update_best_feasible(
                is_feasible=True,
                y=12.0,
                best_feasible=None,
            )
        )
        self.assertTrue(
            may_update_best_feasible(
                is_feasible=True,
                y=10.0,
                best_feasible={"y": 12.0},
            )
        )
        self.assertFalse(
            may_update_best_feasible(
                is_feasible=True,
                y=11.0,
                best_feasible={"y": 10.0},
            )
        )
        self.assertFalse(
            may_update_best_feasible(
                is_feasible=False,
                y=1.0,
                best_feasible=None,
            )
        )

    def test_expected_names_from_active_constraints_skip_z(self) -> None:
        constraints = {
            "A_bending_capacity": {"active": True},
            "Z3_beam_theory_B_L_capacity": {"active": True},
            "C1_concrete_cover_capacity": {"active": False},
            "D2_impact_sound_insulation_capacity": {"active": True},
        }
        names = expected_constraint_names(constraints)
        self.assertEqual(
            names,
            ["A_bending_capacity", "D2_impact_sound_insulation_capacity"],
        )


if __name__ == "__main__":
    unittest.main()

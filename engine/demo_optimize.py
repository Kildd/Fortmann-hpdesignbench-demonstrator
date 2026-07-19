"""
TPE optimization loop for the HPDesignBench demonstrator.

Uses a vendored copy of the HP analysis stack. Emits JSON lines on stdout
so a browser worker (or CLI) can stream progress.

Usage:
  python demo_optimize.py --n-trials 80 --omega-gwp 1 --omega-cost 0
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import traceback
import types
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parent
VENDOR_ROOT = ENGINE_ROOT / "vendor"

# structuralcodes imports triangle at module import time; stub before any analysis import.
if "triangle" not in sys.modules:
    try:
        import triangle as _triangle_mod  # noqa: F401
    except Exception:
        _tri = types.ModuleType("triangle")
        _tri.__hp_stub__ = True  # type: ignore[attr-defined]

        def _triangulate(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("triangle is not available in this environment")

        _tri.triangulate = _triangulate  # type: ignore[attr-defined]
        sys.modules["triangle"] = _tri

for _p in (str(VENDOR_ROOT), str(ENGINE_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.ioh_core.import_specs import (  # noqa: E402
    build_space,
    load_constraint_defaults,
    load_materials_registry,
    load_param_defaults,
    load_problems_combined,
    make_decode,
)
from slab_construction.slabs.hp_slab.analysis import (  # noqa: E402
    analysis,
    resolve_active_constraints,
)
from integrator_util import section_integrator  # noqa: E402
from tpe_simple import IntegerTPE  # noqa: E402

HP_DIR = ENGINE_ROOT / "slab_construction" / "slabs" / "hp_slab"

VAR_LABELS_DE = {
    "geom_h_ges_mm": "Bauhöhe H_ges",
    "geom_t_mm": "Schalendicke t",
    "geom_nt": "Spanngliedanzahl n_t",
    "geom_dy_mm": "Randabstand d_y",
    "mat_conc_fck": "Betonfestigkeit f_ck",
    "reinf_kap_t_percent": "Vorspannungsgrad",
    "reinf_a_tex_mm2": "CFRP-Querschnitt A_tex",
    "geom_t_infill_mm": "Fülldicke",
    "geom_t_screed_mm": "Estrichdicke",
}

CONSTRAINT_LABELS_DE = {
    "A_bending_capacity": "Biegetragfähigkeit",
    "B1a_deflection_by_wmax_capacity": "Durchbiegung w_max",
    "B1b_deflection_by_mcr_capacity": "Durchbiegung über M_cr",
    "B2a_failure_announcement_by_wmin_capacity": "Ankündigung w_min",
    "B2b_failure_announcement_by_mcr_capacity": "Ankündigung über M_cr",
    "C1_concrete_cover_capacity": "Betondeckung",
    "C2_clear_spacing_capacity": "Stababstand",
    "C3_shell_thickness_capacity": "Min. Schalendicke",
    "D1_airborne_sound_insulation_capacity": "Luftschall",
    "D2_impact_sound_insulation_capacity": "Trittschall",
    "Z1_nt_dt_combination_capacity": "n_t–d_y Kombination",
    "Z2_beam_theory_H_L_capacity": "Balkentheorie H/L",
    "Z3_beam_theory_B_L_capacity": "Balkentheorie B/L",
}


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, allow_nan=False) + "\n")
    sys.stdout.flush()


def _geometry_payload(params: dict[str, Any]) -> dict[str, Any]:
    h_ges = float(params.get("geom_h_ges_mm", 0.0) or 0.0)
    ratio = float(params.get("geom_hx_hges_ratio", 0.2) or 0.2)
    hx = ratio * h_ges
    hy = (1.0 - ratio) * h_ges
    return {
        "span_mm": params.get("geom_span_mm"),
        "b_mm": params.get("geom_b_mm"),
        "h_ges_mm": h_ges,
        "hx_hges_ratio": ratio,
        "hx_mm": hx,
        "hy_mm": hy,
        "t_mm": params.get("geom_t_mm"),
        "nt": params.get("geom_nt"),
        "dy_mm": params.get("geom_dy_mm"),
        "t_infill_mm": params.get("geom_t_infill_mm"),
        "t_screed_mm": params.get("geom_t_screed_mm"),
        "t_insulation_mm": params.get("geom_t_insulation_mm"),
        "fck": params.get("mat_conc_fck"),
        "kap_t_percent": params.get("reinf_kap_t_percent"),
        "a_tex_mm2": params.get("reinf_a_tex_mm2"),
    }


def _set_fixed_value(model: dict, name: str, value: Any) -> None:
    """Overlay a fixed parameter by choosing the closest catalog value."""
    if name not in model:
        return
    m = model[name]
    values = m["values"]
    if not values:
        return
    if isinstance(values[0], str):
        try:
            idx = values.index(str(value))
        except ValueError:
            idx = m.get("fixed_idx", 0)
    else:
        target = float(value)
        idx = min(range(len(values)), key=lambda i: abs(float(values[i]) - target))
    m["role"] = "fixed"
    m["fixed_idx"] = idx


def build_problem(
    omega_gwp: float,
    omega_cost: float,
    span_mm: float | None = None,
    load_category: str | None = None,
) -> dict[str, Any]:
    pdef = load_param_defaults(HP_DIR / "parameter_defaults.csv")
    cdef = load_constraint_defaults(HP_DIR / "constraint_defaults.csv")
    problems = load_problems_combined(pdef, cdef, HP_DIR / "problem_list.csv")
    info = problems["1"]
    model = info["model"]

    _set_fixed_value(model, "weight_omega_1_gwp", omega_gwp)
    _set_fixed_value(model, "weight_omega_2_cost", omega_cost)
    if span_mm is not None:
        _set_fixed_value(model, "geom_span_mm", span_mm)
    if load_category is not None:
        _set_fixed_value(model, "loads_category", load_category)

    var_names, lb, ub = build_space(model)
    decode = make_decode(model, var_names)
    materials = load_materials_registry(HP_DIR / "materials.csv")

    seed_params = decode([(a + b) // 2 for a, b in zip(lb, ub)])
    constraints = resolve_active_constraints(seed_params, info["constraints"])

    return {
        "model": model,
        "var_names": var_names,
        "lb": lb,
        "ub": ub,
        "decode": decode,
        "materials": materials,
        "constraints": constraints,
    }


def _evaluate_one(
    x: list[int],
    *,
    trial: int,
    var_names: list[str],
    decode: Any,
    materials: dict,
    constraints: dict,
    best: dict[str, Any] | None,
) -> tuple[float, dict[str, Any], dict[str, Any] | None]:
    params = decode(x)
    try:
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            result = analysis(params, constraints, materials, debug=False)
        y = float(result["y"])
        y_p = float(result["y_p"])
        penalties = {k: float(v) for k, v in result["penalties_"].items()}
        util = {k: float(v) for k, v in result["constraint_values"].items()}
        err = None
    except Exception as exc:  # noqa: BLE001 — keep optimizer alive
        y = float("inf")
        y_p = float("inf")
        penalties = {}
        util = {}
        err = f"{type(exc).__name__}: {exc}"
        params = dict(params)

    decoded_vars = {name: params.get(name) for name in var_names}
    payload: dict[str, Any] = {
        "type": "trial",
        "trial": trial,
        "x": x,
        "vars": decoded_vars,
        "y": y if y != float("inf") else None,
        "y_p": y_p if y_p != float("inf") else None,
        "penalties": penalties,
        "utilizations": util,
        "error": err,
        "geometry": _geometry_payload(params),
    }

    is_best = best is None or (y_p < best["y_p"])
    if is_best and y_p != float("inf"):
        best = {
            "trial": trial,
            "y": y,
            "y_p": y_p,
            "vars": decoded_vars,
            "penalties": penalties,
            "utilizations": util,
            "geometry": payload["geometry"],
        }
        payload["is_best"] = True
        payload["best"] = best
    else:
        payload["is_best"] = False
        payload["best"] = best

    return y_p, payload, best


def run_tpe(
    n_trials: int,
    omega_gwp: float,
    omega_cost: float,
    span_mm: float | None,
    load_category: str | None,
    seed: int = 42,
) -> None:
    problem = build_problem(omega_gwp, omega_cost, span_mm, load_category)
    var_names: list[str] = problem["var_names"]
    lb: list[int] = problem["lb"]
    ub: list[int] = problem["ub"]
    decode = problem["decode"]
    materials = problem["materials"]
    constraints = problem["constraints"]

    _emit(
        {
            "type": "start",
            "n_trials": n_trials,
            "var_names": var_names,
            "var_labels": {k: VAR_LABELS_DE.get(k, k) for k in var_names},
            "constraint_labels": CONSTRAINT_LABELS_DE,
            "omega_gwp": omega_gwp,
            "omega_cost": omega_cost,
            "integrator": section_integrator(),
            "sampler": "tpe_simple",
        }
    )

    sampler = IntegerTPE(
        bounds=list(zip(lb, ub)),
        seed=seed,
        n_startup=min(10, max(3, n_trials // 5)),
    )
    best: dict[str, Any] | None = None

    for trial in range(n_trials):
        x = sampler.ask()
        y_p, payload, best = _evaluate_one(
            x,
            trial=trial,
            var_names=var_names,
            decode=decode,
            materials=materials,
            constraints=constraints,
            best=best,
        )
        sampler.tell(x, y_p)
        _emit(payload)

    _emit(
        {
            "type": "done",
            "best": best,
            "n_trials": n_trials,
            "best_value": best["y_p"] if best else None,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HP shell TPE demonstrator")
    parser.add_argument("--n-trials", type=int, default=60)
    parser.add_argument("--omega-gwp", type=float, default=1.0)
    parser.add_argument("--omega-cost", type=float, default=0.0)
    parser.add_argument("--span-mm", type=float, default=None)
    parser.add_argument("--load-category", type=str, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    try:
        run_tpe(
            n_trials=args.n_trials,
            omega_gwp=args.omega_gwp,
            omega_cost=args.omega_cost,
            span_mm=args.span_mm,
            load_category=args.load_category,
            seed=args.seed,
        )
        return 0
    except Exception:
        _emit({"type": "error", "message": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Moment-curvature and cross-section methods per Eurocode 2.

Provides routines for computing the cracking moment, the SLS/ULS bending
strength, and full as well as simplified moment-curvature (M-κ) diagrams,
plus helpers for building SLS sections and querying section properties.

Production analysis uses the cache pipeline
(:func:`prepare_reference_analysis_cache_EC`,
:func:`prepare_deflection_mk_cache`). Single-section
:func:`calculate_moment_curvature_sls_EC` is the ad-hoc / verification entry
and shares the same simplified primitives as the cache path.

Units: lengths in mm, forces in N, moments in Nmm.

Author: Elliot Melcer
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import time
import warnings
from typing import Iterator

import numpy as np
from scipy.optimize import brentq
from structuralcodes.core._section_results import MomentCurvatureResults
from structuralcodes.geometry import  CompoundGeometry, SurfaceGeometry
from structuralcodes.materials.concrete import Concrete
from structuralcodes.materials.reinforcement import Reinforcement
from structuralcodes.sections import BeamSection

from core.analysis_core.material_methods import create_sls_concrete_EC, TensionStiffeningConcreteLawEC
from slab_construction.slab_construction import MKCurveKey, SectionResultKey, SlabConstruction


DEFLECTION_MK_SIMPLIFICATION = [0.25, 0.50, 0.75]
DEFLECTION_MK_SIMPLIFICATION_SOFTENING = [1.25, 1.50, 1.75]
DEFLECTION_MK_CACHE_POSITIONS = (0.0, 0.5)


@contextmanager
def _mk_stage(
        stage_timings: list[tuple[str, float]] | None,
        name: str,
        *,
        x: float | None = None,
) -> Iterator[None]:
    """Optionally record wall time for one M-κ construction stage."""
    if stage_timings is None:
        yield
        return
    label = name if x is None else f"{name}[x={x}]"
    started = time.perf_counter()
    yield
    stage_timings.append((label, time.perf_counter() - started))


class InvalidSectionForMKError(ValueError):
    """Raised when a section cannot produce a valid M-κ diagram.

    Typical cause: prestress too high, so the section would crush before
    cracking.
    """


@dataclass
class SimplifiedMKParts:
    """Intermediate simplified M-κ ingredients before final assembly.

    The simplified M-κ path is intentionally split into three stages:
    build base characteristic points, optionally splice coordinated softening
    extras, then assemble ``MomentCurvatureResults``. Keeping these values
    explicit lets multi-section deflection preparation detect softening once
    and apply the same extra-point topology to every reference section.
    """

    section: BeamSection
    n: float
    kappa_0: float
    kappa_cr: float
    kappa_eoc: float
    kappa_u: float
    M_cr_Nmm: float
    M_eoc_Nmm: float
    M_u_Nmm: float
    kappa_extra_cr_eoc: np.ndarray
    M_extra_cr_eoc_Nmm: np.ndarray
    kappa_extra_eoc_u: np.ndarray
    M_extra_eoc_u_Nmm: np.ndarray
    kappa_yield: list[float] = field(default_factory=list)
    M_yield_Nmm: list[float] = field(default_factory=list)
    softening_detected: bool = False
    softening_extras_applied: bool = False


def _calculate_cracking_moment_equilibrium_sls_Nmm_EC(
        analysis_sec: BeamSection,
        n: float = 0.0,
        *,
        result_section: BeamSection | None = None,
) -> dict:
    """Find ``M_cr`` by equilibrium with bottom fiber at ``eps_ctm``.

    Shared core for cracking on an already-built SLS section (e.g.
    TENSTIFF in production, or FCTM in verification). Does not build
    materials.

    Parameters
    ----------
    analysis_sec : BeamSection
        Section used for the equilibrium search (and triangulation).
    n : float, optional
        External axial force [N] (positive = tension). Default: ``0.0``.
    result_section : BeamSection or None, optional
        Section stored in the returned dict. Defaults to ``analysis_sec``.

    Returns
    -------
    dict
        Same schema as :func:`calculate_cracking_moment_sls_Nmm_EC`.
    """
    section_out = analysis_sec if result_section is None else result_section

    conc = None
    for geo in analysis_sec.geometry.geometries:
        if hasattr(geo, "concrete") and geo.concrete:
            conc = geo.material
            break
    if conc is None:
        raise ValueError("No concrete geometry found in section")

    Ecm = conc.Ecm
    fctm = conc.fctm
    eps_ctm = fctm / Ecm
    eps_cu1 = -abs(conc.eps_cu1) if hasattr(conc, "eps_cu1") else -0.0035

    _, _, zmin, zmax = analysis_sec.geometry.calculate_extents()
    section_depth = zmax - zmin
    chi_min_physical = (eps_cu1 - eps_ctm) / section_depth

    # Strain profile: eps(z) = eps_0 + chi_y * z
    # Cracking: eps(zmin) = eps_ctm  =>  eps_0 = eps_ctm - chi_y * zmin
    # Crushing bound: eps_top >= eps_cu1
    #   => chi_y >= (eps_cu1 - eps_ctm) / (zmax - zmin)  (lower bound for sagging)

    calculator = analysis_sec.section_calculator
    integration_data = getattr(calculator, "integration_data", None)
    mesh_size = getattr(calculator, "mesh_size", 0.01)

    chi_min = chi_min_physical * 1.001
    chi_max = 1e-3
    ITMAX = 100
    tolerance = 1e-2

    try:
        eps_0_a = eps_ctm - chi_min * zmin
        N_a, _, _, integration_data = calculator.integrator.integrate_strain_response_on_geometry(
            analysis_sec.geometry,
            [eps_0_a, chi_min, 0.0],
            integration_data=integration_data,
            mesh_size=mesh_size,
        )
        # Persist triangulation on the calculator for later M-κ stages.
        if calculator.integration_data is None and integration_data is not None:
            calculator.integration_data = integration_data
        dn_a = N_a - n

        eps_0_b = eps_ctm - chi_max * zmin
        N_b, _, _, _ = calculator.integrator.integrate_strain_response_on_geometry(
            analysis_sec.geometry,
            [eps_0_b, chi_max, 0.0],
            integration_data=integration_data,
            mesh_size=mesh_size,
        )
        dn_b = N_b - n

        if dn_a * dn_b > 0:
            if dn_a > 0 and dn_b > 0:
                reason = (
                    "Prestress too high - section would crush before cracking "
                    "(N > 0 throughout valid range)"
                )
            else:
                reason = "No equilibrium solution in valid curvature range"
            return {
                "section": section_out,
                "m_cr": float("-inf"),
                "strain_profile": [0.0, chi_min_physical, 0.0],
                "valid": False,
                "reason": reason,
                "chi_min_physical": chi_min_physical,
            }

        chi_c = chi_min
        dn_c = dn_a
        it = 0
        while abs(dn_a - dn_b) > tolerance and it < ITMAX:
            chi_c = (chi_min + chi_max) / 2.0
            eps_0_c = eps_ctm - chi_c * zmin
            N_c, _, _, _ = calculator.integrator.integrate_strain_response_on_geometry(
                analysis_sec.geometry,
                [eps_0_c, chi_c, 0.0],
                integration_data=integration_data,
                mesh_size=mesh_size,
            )
            dn_c = N_c - n
            if dn_c * dn_a < 0:
                chi_max = chi_c
                dn_b = dn_c
            else:
                chi_min = chi_c
                dn_a = dn_c
            it += 1

        if it >= ITMAX:
            print(f"Warning: Maximum iterations reached. Force imbalance: {dn_c:.2f} N")

        chi_y_eq = chi_c
        eps_0_eq = eps_ctm - chi_y_eq * zmin
        strain_profile = [eps_0_eq, chi_y_eq, 0.0]

        eps_top = eps_0_eq + chi_y_eq * zmax
        if eps_top < eps_cu1:
            return {
                "section": section_out,
                "m_cr": float("-inf"),
                "strain_profile": strain_profile,
                "valid": False,
                "reason": (
                    "Solution exceeds concrete crushing strain "
                    f"(eps_top={eps_top:.4f} < eps_cu1={eps_cu1:.4f})"
                ),
            }

        forces = calculator.integrate_strain_profile(
            strain=strain_profile,
            integrate="stress",
        )
        return {
            "section": section_out,
            "m_cr": forces.m_y,
            "strain_profile": strain_profile,
            "valid": True,
            "reason": None,
            "eps_top": eps_top,
        }
    except Exception as e:
        print(f"Error in equilibrium calculation: {e}")
        raise


def calculate_cracking_moment_sls_Nmm_EC(
        section: BeamSection,
        n: float = 0.0,
) -> dict:
    """Calculate the cracking moment on the given section as-is.

    Finds the strain profile where the bottom fiber reaches
    ``eps_ctm = fctm / Ecm`` while maintaining equilibrium with the
    applied axial force ``n``. The section's existing concrete constitutive
    law is used (no ``sls_section_EC`` / ``deepcopy``). Analyses ``section``
    in place and warms its ``integration_data`` for later reuse.


    Parameters
    ----------
    section : BeamSection
        Section to analyse (already configured with the desired SLS law).
    n : float, optional
        Applied axial force [N] (positive = tension, negative =
        compression). Default: ``0.0``.

    Returns
    -------
    dict
        Result with the keys:

        - ``section`` : BeamSection — the input ``section``.
        - ``m_cr`` : float — cracking moment [Nmm], or ``float('-inf')``
          if the section crushes before cracking.
        - ``strain_profile`` : list — ``[eps_0, chi_y, chi_z]`` at cracking.
        - ``valid`` : bool — ``True`` if a physically valid solution was found.
        - ``reason`` : str or None — explanation if invalid, else ``None``.
        - ``chi_min_physical`` : float — present only on the invalid branch;
          the lower physical curvature bound [1/mm].
        - ``eps_top`` : float — present only on the valid branch; top-fiber
          strain [-] of the solution.

    Raises
    ------
    ValueError
        If no concrete geometry is found in the section.

    Notes
    -----
    Strain profile convention: ``eps(z) = eps_0 + chi_y * z``. For sagging
    bending ``chi_y`` is negative, so the crushing limit acts as a lower
    bound on the curvature.
    """
    return _calculate_cracking_moment_equilibrium_sls_Nmm_EC(
        section,
        n=n,
        result_section=section,
    )


def calculate_bending_strength_Nmm_EC(section: BeamSection, n: float = 0.0) -> dict:
    """Calculate bending strength on the given section as-is.

    Uses ``section.section_calculator.calculate_bending_strength`` directly.
    Does **not** call :func:`sls_section_EC` or ``deepcopy``; the section's
    existing constitutive law is used and triangulation on its calculator
    is reused.

    Pass an already-built SLS section (e.g. TENSTIFF / NONE) or ULS section
    depending on the limit state you want. Limit-state conversion is the
    caller's responsibility.

    Parameters
    ----------
    section : BeamSection
        Section to analyse (already configured with the desired materials).
    n : float, optional
        Applied axial force [N] (positive = tension). Default: ``0.0``.

    Returns
    -------
    dict
        Result with the keys:

        - ``section`` : BeamSection — the input ``section``.
        - ``m_u`` : float or None — bending strength [Nmm], or ``None``
          if the moment cannot be taken by the section.
        - ``strain_profile`` : list or None — ``[eps_0, chi_y, 0.0]`` at
          ultimate, or ``None`` if invalid.
        - ``valid`` : bool — ``True`` if a valid solution was found.
        - ``reason`` : str or None — failure reason if invalid, else ``None``.

    Raises
    ------
    ValueError
        For any ValueError other than the section being unable to take the
        moment (such errors are treated as real bugs and re-raised).
    """
    try:
        bending_strength_result = section.section_calculator.calculate_bending_strength(
            n=n
        )
    except ValueError as e:
        if "cannot be taken by section" in str(e):
            return {
                "section": section,
                "m_u": None,
                "strain_profile": None,
                "valid": False,
                "reason": str(e),
            }
        raise

    return {
        "section": section,
        "m_u": bending_strength_result.m_y,
        "strain_profile": [
            bending_strength_result.eps_a,
            bending_strength_result.chi_y,
            0.0,
        ],
        "valid": True,
        "reason": None,
    }


def calculate_moment_curvature_sls_EC(
        section: BeamSection,
        n: float = 0.0,
        constitutive_law: str = "TENSTIFF_PARABOLIC",
        simplification: bool | int | float | list[float] | tuple[float, ...] = False,
        simplification_softening: int | float | list[float] | tuple[float, ...] | None = None,
        mk_softening_active: bool | None = None,
        *,
        m_k_num_points: int,
        debug: bool = False,
) -> MomentCurvatureResults:
    """Ad-hoc / verification M-κ entry for a single section.

    Builds one SLS section with ``constitutive_law``, then dispatches to the
    full or simplified engine. The simplified path uses the same primitives
    as production
    (:func:`_build_simplified_mk_parts`,
    :func:`_add_softening_extras_to_simplified_mk_parts`,
    :func:`_assemble_simplified_mk_results`).

    Production deflection / B1a/B2a analysis does **not** call this function;
    it uses :func:`prepare_deflection_mk_cache` /
    :func:`prepare_coordinated_simplified_mk_cache_sls_EC` so multiple
    reference sections share softening topology and ``M_cr`` is stored for
    B1b/B2b/ζ.

    Parameters
    ----------
    section : BeamSection
        Reference cross-section (geometry + materials). An SLS section with
        ``constitutive_law`` is built internally for the M-κ calculation.
    n : float, optional
        Axial force [N]. Default: ``0.0``.
    constitutive_law : str, optional
        Keyword for the concrete constitutive law. Default:
        ``"TENSTIFF_PARABOLIC"``.
    simplification : bool or int or float or sequence of floats, optional
        ``False`` uses the full method; ``True``, a positive number, or
        explicit fractions use the simplified method. Fraction values may
        lie in ``(0, 1)`` (between ``kappa_cr`` and ``kappa_eoc``) or
        ``(1, 2)`` (between ``kappa_eoc`` and ``kappa_u``). Default:
        ``False``.
    simplification_softening : int or float or sequence of floats or None, optional
        Extra fractions for the simplified path when softening extras are
        active. Same fraction encoding as ``simplification``. ``None`` means
        no softening extras. Default: ``None``.
    mk_softening_active : bool or None, optional
        Controls whether ``simplification_softening`` is applied:

        - ``True`` — always insert softening extras (if provided).
        - ``False`` — never insert softening extras.
        - ``None`` — auto-detect from pre-EOC samples vs ``M_eoc``
          (single-section default).

        For multi-section spatial blending use
        :func:`prepare_coordinated_simplified_mk_cache_sls_EC`. Default:
        ``None``.
    m_k_num_points : int
        Number of uniformly spaced curvature points used by the full M-κ
        method (from near-zero to ultimate curvature, before inserting
        ``kappa_cr``). Also used when estimating ``kappa_0`` on the
        simplified path.
    debug : bool, optional
        Enables debug output. Default: ``False``.

    Returns
    -------
    MomentCurvatureResults
        The complete, force-controlled M-κ curve.

    Raises
    ------
    ValueError
        If ``simplification`` is neither ``False``, ``True``, a positive
        number, nor a sequence of fractions.
    """
    if m_k_num_points < 2:
        raise ValueError(f"m_k_num_points must be >= 2, got {m_k_num_points}")

    sls_sec = sls_section_EC(section, constitutive_law)

    if simplification is False:
        results = _full_moment_curvature_method(
            section=sls_sec,
            n=n,
            m_k_num_points=m_k_num_points,
            debug=debug,
        )
    elif (
        simplification is True
        or (isinstance(simplification, (int, float)) and simplification > 0)
        or isinstance(simplification, (list, tuple, np.ndarray))
    ):
        parts = _build_simplified_mk_parts(
            sls_sec,
            simplification=simplification,
            n=n,
            m_k_num_points=m_k_num_points,
            debug=debug,
        )
        if mk_softening_active is None:
            apply_softening_extras = parts.softening_detected
        else:
            apply_softening_extras = bool(mk_softening_active)

        if simplification_softening is not None and apply_softening_extras:
            _add_softening_extras_to_simplified_mk_parts(
                parts,
                simplification_softening=simplification_softening,
                debug=debug,
            )
            if debug:
                source = (
                    "auto-detected"
                    if mk_softening_active is None
                    else f"forced mk_softening_active={mk_softening_active}"
                )
                print(
                    f"[softening] applied ({source}): "
                    f"|M_eoc|={abs(parts.M_eoc_Nmm) / 1e6:.3f} kNm"
                )
        elif debug and simplification_softening is not None:
            source = (
                "auto-detected"
                if mk_softening_active is None
                else f"forced mk_softening_active={mk_softening_active}"
            )
            print(
                f"[softening] skipped ({source}): "
                f"|M_eoc|={abs(parts.M_eoc_Nmm) / 1e6:.3f} kNm"
            )

        results = _assemble_simplified_mk_results(parts)
        if debug:
            _print_simplified_mk_debug_table(parts, results)
    else:
        raise ValueError(
            "simplification must be False, True, a positive number, "
            f"or a sequence of fractions, got {simplification!r}"
        )

    return _ensure_force_controlled(results)


def store_cracking_moment_cache_sls_EC(
        slab_construction: SlabConstruction,
        x: float,
        n: float,
        result: dict,
) -> SectionResultKey:
    """Store an SLS cracking-moment result for B1b/B2b and deflection ζ.

    Production obtains ``result`` from the TENSTIFF M-κ path (same
    equilibrium ``M_cr`` as the historical FCTM law up to ``fctm``).
    """
    key = SectionResultKey(
        result_type="M_cr",
        x=x,
        limit_state="SLS",
        n=n,
    )
    slab_construction.analysis_cache.m_cr[key] = result
    return key


def prepare_bending_strength_cache_uls_EC(
        slab_construction: SlabConstruction,
        x: float,
        n: float = 0.0,
        *,
        flipped: bool = False,
) -> SectionResultKey:
    """Prepare and cache the ULS bending strength result for one section.

    Uses the cached reference section from ``section_at`` as-is (already
    ULS). Does not convert materials, so triangulation stays on that section.
    """
    cache = slab_construction.analysis_cache
    key = SectionResultKey(
        result_type="M_u",
        x=x,
        limit_state="ULS",
        n=n,
        flipped=flipped,
    )
    if key not in cache.m_u:
        section = cache.require_section(x)
        if flipped:
            section = flipped_section(section)
        cache.m_u[key] = calculate_bending_strength_Nmm_EC(
            section, n=n
        )
    return key


def make_mk_curve_key_sls_EC(
        *,
        constitutive_law: str,
        simplification: bool | int | float | list[float] | tuple[float, ...],
        simplification_softening: int | float | list[float] | tuple[float, ...] | None,
        n: float,
        m_k_num_points: int,
) -> MKCurveKey:
    """Build the canonical cache key for one SLS M-κ curve configuration."""

    def _key_value(value):
        if isinstance(value, (list, tuple, np.ndarray)):
            return tuple(value)
        return value

    is_full = simplification is False
    return MKCurveKey(
        limit_state="SLS",
        constitutive_law=constitutive_law,
        method="full" if is_full else "simplified",
        simplification=False if is_full else _key_value(simplification),
        softening=None if is_full else _key_value(simplification_softening),
        n=n,
        m_k_num_points=m_k_num_points,
    )


def prepare_mk_cache_sls_EC(
        slab_construction: SlabConstruction,
        n: float = 0.0,
        constitutive_law: str = "TENSTIFF_PARABOLIC",
        simplification: bool | int | float | list[float] | tuple[float, ...] = False,
        simplification_softening: int | float | list[float] | tuple[float, ...] | None = None,
        *,
        m_k_num_points: int = 40,
        positions: tuple[float, ...] = DEFLECTION_MK_CACHE_POSITIONS,
        stage_timings: list[tuple[str, float]] | None = None,
) -> MKCurveKey:
    """Prepare and cache SLS M-κ curves for reference sections.

    Also stores SLS ``M_cr`` at each position (from the same SLS section
    used for M-κ) for B1b/B2b and deflection ζ via ``require_m_cr``.

    The generated key is returned so consumers can require the exact same
    configuration from :attr:`SlabConstruction.analysis_cache`.
    """
    cache = slab_construction.analysis_cache
    key = make_mk_curve_key_sls_EC(
        constitutive_law=constitutive_law,
        simplification=simplification,
        simplification_softening=simplification_softening,
        n=n,
        m_k_num_points=m_k_num_points,
    )
    if key in cache.mk_curves:
        return key

    sections = {x: cache.require_section(x) for x in positions}

    def _store_m_cr(x: float, m_cr_result: dict) -> None:
        store_cracking_moment_cache_sls_EC(
            slab_construction, x=x, n=n, result=m_cr_result
        )

    if simplification is False:
        curves = {}
        for x, section in sections.items():
            sls_sec = sls_section_EC(section, constitutive_law)
            _store_m_cr(x, calculate_cracking_moment_sls_Nmm_EC(sls_sec, n=n))
            curves[x] = _ensure_force_controlled(
                _full_moment_curvature_method(
                    section=sls_sec,
                    n=n,
                    m_k_num_points=m_k_num_points,
                )
            )
        cache.mk_curves[key] = curves
        cache.mk_metadata[key] = {
            "method": "full",
        }
    else:
        # Build simplified M-κ on one TENSTIFF section per position:
        # M_cr, M_u, κ₀, EOC, and extras share that section/calculator.
        # M_cr is also written to analysis_cache for B1b/B2b/ζ.
        curves, softening_detected, softening_extras_applied = prepare_coordinated_simplified_mk_cache_sls_EC(
            sections,
            simplification=simplification,
            simplification_softening=simplification_softening,
            n=n,
            constitutive_law=constitutive_law,
            m_k_num_points=m_k_num_points,
            stage_timings=stage_timings,
            on_m_cr=_store_m_cr,
        )
        cache.mk_curves[key] = curves
        cache.mk_metadata[key] = {
            "method": "simplified",
            "softening_detected": softening_detected,
            "softening_extras_applied": softening_extras_applied,
            "softening_active": softening_extras_applied,
        }
    return key


def prepare_reference_analysis_cache_EC(
        slab_construction: SlabConstruction,
        n: float = 0.0,
        *,
        mk_configs: tuple[dict, ...] | None = None,
) -> None:
    """Prepare the standard reference-section cache used by analysis workflows.

    For each reference position this stores:

    - the reference section from ``section_at``
    - ULS ``M_u`` for capacity checks

    SLS ``M_cr`` for B1b/B2b and deflection ζ is stored later by
    :func:`prepare_mk_cache_sls_EC` / :func:`prepare_deflection_mk_cache`
    from the TENSTIFF section (no separate FCTM prep).
    """
    cache = slab_construction.analysis_cache
    for x in DEFLECTION_MK_CACHE_POSITIONS:
        if x not in cache.sections:
            cache.sections[x] = slab_construction.slab.section_at(x)
        prepare_bending_strength_cache_uls_EC(slab_construction, x=x, n=n)

    for config in mk_configs or ():
        prepare_mk_cache_sls_EC(slab_construction, n=n, **config)


def prepare_deflection_mk_cache(
        slab_construction: SlabConstruction,
        n: float = 0.0,
        constitutive_law: str = "TENSTIFF_PARABOLIC",
        *,
        stage_timings: list[tuple[str, float]] | None = None,
) -> None:
    """Prepare coordinated simplified SLS M-κ curves for deflection checks.

    Expects reference sections already in
    :attr:`SlabConstruction.analysis_cache.sections`. Builds SLS TENSTIFF
    M-κ curves once (``M_cr``, SLS ``M_u``, ``κ₀``, EOC, extras on that SLS
    section), stores ``M_cr`` for B1b/B2b/ζ, coordinates softening extras
    across all reference positions, and stores the M-κ result for B1a/B2a
    reuse. ULS capacity checks use a separate ULS path and are not part of
    this cache.

    Parameters
    ----------
    stage_timings : list or None, optional
        If provided, appends ``(stage_name, seconds)`` pairs for profiling.
        Default is ``None`` (no timing overhead beyond a null check).
    """
    prepare_mk_cache_sls_EC(
        slab_construction,
        n=n,
        constitutive_law=constitutive_law,
        simplification=DEFLECTION_MK_SIMPLIFICATION,
        simplification_softening=DEFLECTION_MK_SIMPLIFICATION_SOFTENING,
        stage_timings=stage_timings,
    )


def prepare_coordinated_simplified_mk_cache_sls_EC(
        sections: dict[float, BeamSection],
        simplification: bool | int | float | list[float] | tuple[float, ...] = True,
        simplification_softening: int | float | list[float] | tuple[float, ...] | None = None,
        n: float = 0.0,
        constitutive_law: str = "TENSTIFF_PARABOLIC",
        *,
        m_k_num_points: int = 40,
        debug: bool = False,
        stage_timings: list[tuple[str, float]] | None = None,
        on_m_cr=None,
) -> tuple[dict[float, MomentCurvatureResults], bool, bool]:
    """Build coordinated simplified SLS M-κ curves for several reference sections.

    Each reference section is converted once to an **SLS** section with
    ``constitutive_law`` (typically TENSTIFF). All SLS M-κ quantities
    (``M_cr``, SLS ``M_u``, ``κ₀``, EOC, extras) are computed on that same
    SLS section. ULS bending strength is **not** part of this path; it is
    computed separately on the cached ULS reference section via
    :func:`calculate_bending_strength_Nmm_EC`.
    If any section detects softening and ``simplification_softening`` is
    provided, softening extras are spliced into **all** curves so they share
    the same polyline topology for spatial blending.

    Parameters
    ----------
    sections : dict[float, BeamSection]
        Map of normalized position → reference section
        (e.g. ``{0.0: ..., 0.5: ...}`` from ``analysis_cache.sections``).
    simplification, simplification_softening, n, constitutive_law, m_k_num_points
        Same meaning as :func:`calculate_moment_curvature_sls_EC`.
    stage_timings : list or None, optional
        Optional profiling sink for stage wall times.
    on_m_cr : callable or None, optional
        If given, called as ``on_m_cr(x, m_cr_result)`` immediately after
        each section's cracking-moment solve (including invalid results,
        before ``InvalidSectionForMKError`` is raised). Used to populate
        ``analysis_cache.m_cr`` for B1b/B2b/ζ.

    Returns
    -------
    curves : dict[float, MomentCurvatureResults]
        Force-controlled simplified M-κ curve per position.
    softening_detected : bool
        ``True`` if any section has ``|M| > |M_eoc|`` among
        ``{M_cr}`` and the base pre-EOC extra points.
    softening_extras_applied : bool
        ``True`` if softening was detected and ``simplification_softening``
        was provided, so softening extras were spliced into all curves.
    """
    if not sections:
        raise ValueError("sections must be a non-empty mapping")

    parts_by_x: dict[float, SimplifiedMKParts] = {}
    for x, section in sections.items():
        with _mk_stage(stage_timings, "sls_section_EC", x=x):
            sls_sec = sls_section_EC(section, constitutive_law)
        with _mk_stage(stage_timings, "build_simplified_mk_parts", x=x):
            parts_by_x[x] = _build_simplified_mk_parts(
                sls_sec,
                simplification=simplification,
                n=n,
                m_k_num_points=m_k_num_points,
                debug=debug,
                stage_timings=stage_timings,
                stage_x=x,
                on_m_cr=(
                    (lambda result, _x=x: on_m_cr(_x, result))
                    if on_m_cr is not None
                    else None
                ),
            )

    softening_detected = any(p.softening_detected for p in parts_by_x.values())
    softening_extras_applied = softening_detected and simplification_softening is not None
    if softening_extras_applied:
        for x, parts in parts_by_x.items():
            with _mk_stage(stage_timings, "softening_extras", x=x):
                _add_softening_extras_to_simplified_mk_parts(
                    parts,
                    simplification_softening=simplification_softening,
                    debug=debug,
                )

    curves: dict[float, MomentCurvatureResults] = {}
    for x, parts in parts_by_x.items():
        with _mk_stage(stage_timings, "assemble_and_force_control", x=x):
            curves[x] = _ensure_force_controlled(
                _assemble_simplified_mk_results(parts)
            )
    return curves, softening_detected, softening_extras_applied


def _ensure_force_controlled(results: MomentCurvatureResults) -> MomentCurvatureResults:
    """Enforce a force-controlled M-κ diagram with monotonic moment magnitude.

    Whenever ``|m[i+1]| < |m[i]|``, collects all dip indices until the first
    ``j`` where ``|m[j]| > |m[i]|``, inserts an interpolated point
    (κ_new, m[i]) at ``i+1``, and removes the dip indices. If the moment
    never recovers, the tail is truncated.

    Parameters
    ----------
    results : MomentCurvatureResults
        Moment-curvature results (modified in place).

    Returns
    -------
    MomentCurvatureResults
        The same object with corrected ``m_y`` and ``chi_y`` arrays.
    """

    # Work with a single list of (moment, curvature) pairs so the two arrays
    # can never be modified independently and get out of sync.
    pairs = list(zip(results.m_y, results.chi_y))

    i = 0
    while i < len(pairs) - 1:

        if abs(pairs[i + 1][0]) < abs(pairs[i][0]):
            # ----------------------------------------------------------------
            # Dip detected: advance j until the moment recovers past m[i].
            # ----------------------------------------------------------------
            j = i + 1
            while j < len(pairs) and abs(pairs[j][0]) <= abs(pairs[i][0]):
                j += 1

            m_peak = pairs[i][0]  # signed peak moment (negative)

            if j < len(pairs):
                # ------------------------------------------------------------
                # Indices i+1 … j-2: set moment to m_peak, curvature unchanged.
                # ------------------------------------------------------------
                for k in range(i + 1, j - 1):
                    pairs[k] = (m_peak, pairs[k][1])

                # ------------------------------------------------------------
                # Index j-1: set moment to m_peak, interpolate curvature
                # between the original values at j-1 and j at M = m_peak.
                # ------------------------------------------------------------
                m_before = pairs[j - 1][0]
                m_after = pairs[j][0]
                chi_before = pairs[j - 1][1]
                chi_after = pairs[j][1]

                t = (m_peak - m_before) / (m_after - m_before)
                pairs[j - 1] = (m_peak, chi_before + t * (chi_after - chi_before))

            else:
                # ------------------------------------------------------------
                # Moment never recovers: set all remaining to m_peak,
                # curvatures unchanged.
                # ------------------------------------------------------------
                for k in range(i + 1, len(pairs)):
                    pairs[k] = (m_peak, pairs[k][1])

        i += 1

    # Unzip pairs and write corrected arrays back to the results object
    moments, curvatures = zip(*pairs) if pairs else ([], [])
    results.m_y = np.array(moments)
    results.chi_y = np.array(curvatures)

    return results


def _full_moment_curvature_method(section: BeamSection,
                                  n: float = 0.0,
                                  *,
                                  m_k_num_points: int,
                                  debug: bool = False) -> MomentCurvatureResults:
    """Compute the full moment-curvature diagram for a section and axial force.

    Moments are computed for a list of curvatures that includes the cracking
    curvature, using ``calculate_moment_curvature()`` from structuralcodes.
    The cracking point is inserted exactly to capture the cracking behavior
    correctly. If the section is prestressed, the prestress curvature point
    (κ₀, M=0) is added.

    Parameters
    ----------
    section : BeamSection
        Section to analyze.
    n : float, optional
        Axial force [N]. Default: ``0.0``.
    m_k_num_points : int
        Number of uniformly spaced curvature points from near-zero to ultimate
        curvature.
    debug : bool, optional
        Enables debug output. Default: ``False``.

    Returns
    -------
    MomentCurvatureResults
        The full M-κ results.

    Raises
    ------
    InvalidSectionForMKError
        If the cracking moment is invalid, so a full M-κ diagram cannot be
        built.
    """
    # ------------------------------------
    # Build custom curvature list to be evaluated for moment-curvature-diagram
    # Must include exactly the point of cracking to accurately reflect correct
    # cracking behavior
    # ------------------------------------

    # Get bending strength strain profile
    m_u_res = calculate_bending_strength_Nmm_EC(section, n=n)
    eps_0, chi_u, _ = m_u_res["strain_profile"]

    # Get curvature at cracking
    M_cr_result = calculate_cracking_moment_sls_Nmm_EC(section)
    if not M_cr_result.get("valid", True):
        raise InvalidSectionForMKError(
            f"Cannot build full M-K diagram: cracking moment invalid "
            f"({M_cr_result.get('reason', 'unknown')})"
        )
    M_cr = M_cr_result["m_cr"]
    sp = section.section_calculator.calculate_strain_profile(0, M_cr, 0)
    kappa_cr = sp.chi_y

    # Standard-chi-Array + κ_cr deterministisch einfügen
    chi_default = np.linspace(-1e-8, chi_u, m_k_num_points)
    chi_with_crack = np.sort(np.concatenate([chi_default, [kappa_cr]]))[::-1]  # für negative Krümmungen umkehren

    # -----------------------------------
    # Get standard M-κ curve from library
    #------------------------------------
    results = section.section_calculator.calculate_moment_curvature(
        n=n,
        chi = chi_with_crack
    )

    # FIX SIGNS - Library may return negative values
    results.m_y = -np.abs(results.m_y)  # Make consistently negative
    results.chi_y = -np.abs(results.chi_y)  # Make consistently negative

    # Check for prestressed reinforcement
    has_prestress = False
    for pg in section.geometry.point_geometries:
        if hasattr(pg.material, 'initial_strain') and pg.material.initial_strain != 0:
            has_prestress = True
            break

    if not has_prestress:
        return results  # Not prestressed, return as-is

    # -------------------------------------------------------
    # Calculate initial state point (κ₀, M=0)
    # -------------------------------------------------------

    kappa_0 = _calculate_kappa_0(section, n=n, debug=debug)

    # -------------------------------------------------------
    # Stitch together moments and curvatures
    # -------------------------------------------------------

    # Add single initial state point at beginning
    moments_combined = np.concatenate([[0.0], results.m_y])
    curvatures_combined = np.concatenate([[kappa_0], results.chi_y])

    # Update results object
    results.m_y = moments_combined
    results.chi_y = curvatures_combined

    # Update other arrays to match length (if they exist)
    if hasattr(results, 'eps_a') and results.eps_a is not None:
        results.eps_a = np.concatenate([[0.0], results.eps_a])

    if debug:
        print("\n[DEBUG] Prestressed M-κ curve:")
        print(f"  Added initial state: (κ={kappa_0:.9f} 1/mm, M=0)")
        print(f"  Library starts at: (κ={results.chi_y[1]:.9f} 1/mm, M={results.m_y[1] / 1e6:.3f} kNm)")
        print(f"  Total points: {len(moments_combined)}")

    return results


def _kappa_extras_from_fractions(
        fractions,
        kappa_cr: float,
        kappa_eoc: float,
        kappa_u: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Map fraction values to extra curvatures on cr–EOC and EOC–u intervals.

    Parameters
    ----------
    fractions : sequence of float
        Each value must lie in ``(0, 1)`` or ``(1, 2)`` (endpoints excluded):

        - ``v ∈ (0, 1)`` → ``κ = κ_cr + v * (κ_eoc − κ_cr)``
        - ``v ∈ (1, 2)`` → ``κ = κ_eoc + (v − 1) * (κ_u − κ_eoc)``
    kappa_cr, kappa_eoc, kappa_u : float
        Characteristic curvatures [1/mm].

    Returns
    -------
    kappa_cr_eoc : ndarray
        Extra curvatures between cracking and end-of-cracking, sorted.
    kappa_eoc_u : ndarray
        Extra curvatures between end-of-cracking and ultimate, sorted.

    Raises
    ------
    ValueError
        If ``fractions`` is empty/not 1D, or any value is outside
        ``(0, 1) ∪ (1, 2)``.
    """
    values = np.asarray(fractions, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("fractions must be a non-empty 1D sequence.")

    kappa_cr_eoc: list[float] = []
    kappa_eoc_u: list[float] = []
    for v in np.sort(values):
        if 0.0 < v < 1.0:
            kappa_cr_eoc.append(kappa_cr + v * (kappa_eoc - kappa_cr))
        elif 1.0 < v < 2.0:
            kappa_eoc_u.append(kappa_eoc + (v - 1.0) * (kappa_u - kappa_eoc))
        else:
            raise ValueError(
                "Each simplification fraction must satisfy "
                "0 < value < 1 (cr–EOC) or 1 < value < 2 (EOC–u), "
                f"got {v!r}."
            )

    return np.asarray(kappa_cr_eoc, dtype=float), np.asarray(kappa_eoc_u, dtype=float)


def _parse_simplification_extras(
        simplification,
        kappa_cr: float,
        kappa_eoc: float,
        kappa_u: float,
        *,
        param_name: str = "simplification",
) -> tuple[np.ndarray, np.ndarray]:
    """Parse a simplification / softening extras specification into κ arrays.

    Returns
    -------
    kappa_cr_eoc, kappa_eoc_u : ndarray
        Extra curvatures on the cr–EOC and EOC–u intervals.
    """
    if simplification is True or simplification is None:
        return np.array([], dtype=float), np.array([], dtype=float)

    if type(simplification) is int:
        if simplification < 1:
            raise ValueError(f"If {param_name} is an int, it must be >= 1.")
        return (
            np.linspace(kappa_cr, kappa_eoc, simplification + 2)[1:-1],
            np.array([], dtype=float),
        )

    if type(simplification) is float:
        return _kappa_extras_from_fractions(
            [simplification], kappa_cr, kappa_eoc, kappa_u,
        )

    if isinstance(simplification, (list, tuple, np.ndarray)):
        return _kappa_extras_from_fractions(
            simplification, kappa_cr, kappa_eoc, kappa_u,
        )

    raise TypeError(
        f"{param_name} must be one of: None, True, int >= 1, "
        "float with 0 < value < 1 or 1 < value < 2, "
        "or a sequence of floats in (0, 1) U (1, 2) "
        f"(got {type(simplification).__name__})"
    )


def _build_simplified_mk_parts(
        section: BeamSection,
        simplification=None,
        n: float = 0.0,
        *,
        m_k_num_points: int,
        debug: bool = False,
        stage_timings: list[tuple[str, float]] | None = None,
        stage_x: float | None = None,
        on_m_cr=None,
) -> SimplifiedMKParts:
    """Build base simplified SLS M-κ parts (no softening extras yet).

    ``section`` must already be an **SLS** TENSTIFF section. SLS ``M_cr``,
    SLS ``M_u``, ``κ₀``, EOC, yield, and extras are all computed on this
    same SLS section so triangulation / ``integration_data`` is shared.
    Do not pass a ULS section here.
    """
    concrete_sls = get_concrete(section)
    law = concrete_sls.constitutive_law
    eps_F_t = law.eps_F_t

    if not isinstance(law, TensionStiffeningConcreteLawEC):
        raise Exception("Simplified M-K-Line only implemented for TENSTIFF_PARABOLIC")

    with _mk_stage(stage_timings, "m_cr", x=stage_x):
        m_cr_result = calculate_cracking_moment_sls_Nmm_EC(section, n=n)
        if on_m_cr is not None:
            on_m_cr(m_cr_result)
        if not m_cr_result.get("valid", True):
            raise InvalidSectionForMKError(
                f"Cannot build simplified M-K diagram: cracking moment invalid "
                f"({m_cr_result.get('reason', 'unknown')})"
            )
        M_cr_Nmm = m_cr_result["m_cr"]
        kappa_cr = m_cr_result["strain_profile"][1]

    with _mk_stage(stage_timings, "m_u_sls", x=stage_x):
        ultimate_result = calculate_bending_strength_Nmm_EC(section, n=n)
        if (
            not ultimate_result.get("valid", True)
            or ultimate_result.get("strain_profile") is None
            or ultimate_result.get("m_u") is None
        ):
            raise InvalidSectionForMKError(
                "Cannot build simplified M-K diagram: SLS bending strength invalid "
                f"({ultimate_result.get('reason', 'unknown')})"
            )
        M_u_Nmm = ultimate_result["m_u"]
        _, kappa_u, _ = ultimate_result["strain_profile"]

    # Prestressing Point — initial curvature from initial tangent stiffness
    with _mk_stage(stage_timings, "kappa_0", x=stage_x):
        kappa_0 = _calculate_kappa_0(section, n=n, debug=debug)

    # End of Cracking Point
    with _mk_stage(stage_timings, "eoc", x=stage_x):
        eoc_results = _calculate_section_state_from_bottom_strain_sls(
            section,
            n=n,
            eps_bot=eps_F_t,
            method="brentq",
            bracket=(kappa_cr, kappa_u),
            tolerance=1e-1,
        )
    if not eoc_results or not eoc_results.get("valid", False):
        raise InvalidSectionForMKError(
            f"Cannot build simplified M-K diagram: EOC solve failed "
            f"({eoc_results.get('reason', 'unknown') if eoc_results else 'unknown'})"
        )

    _, kappa_eoc, _ = eoc_results["strain_profile"]
    M_eoc_Nmm = eoc_results["m_y"]

    # Yielding Point
    with _mk_stage(stage_timings, "yield", x=stage_x):
        reinforcement, _ = get_reinforcement(section)
        fyk = reinforcement.fyk
        ftk = reinforcement.ftk
        if not fyk == ftk:
            strain = section.section_calculator.find_equilibrium_fixed_pivot(
                section.geometry, n, yielding=True
            )
            kappa_yield = [strain[1]]
            mkd_yield = section.section_calculator.calculate_moment_curvature(
                n=n, chi=[kappa_yield[0]]
            )
            M_yield_Nmm = [mkd_yield.m_y[0]]
        else:
            kappa_yield = []
            M_yield_Nmm = []

    # Extra Points (base)
    if simplification is False:
        raise ValueError(
            "simplification=False means this simplified method should not be called. "
            "Handle this case higher up in the call chain."
        )

    with _mk_stage(stage_timings, "extra_points", x=stage_x):
        kappa_extra_cr_eoc, kappa_extra_eoc_u = _parse_simplification_extras(
            simplification, kappa_cr, kappa_eoc, kappa_u, param_name="simplification",
        )

        # Compute Extra Moments
        def _moments_at(kappa_arr: np.ndarray):
            if kappa_arr.size == 0:
                return np.array([], dtype=float)
            return np.asarray(
                section.section_calculator.calculate_moment_curvature(
                    n=n, chi=kappa_arr
                ).m_y,
                dtype=float,
            )

        M_extra_cr_eoc_Nmm = _moments_at(kappa_extra_cr_eoc)
        M_extra_eoc_u_Nmm = _moments_at(kappa_extra_eoc_u)

    m_pre_eoc = np.concatenate(([M_cr_Nmm], M_extra_cr_eoc_Nmm))
    softening_detected = bool(np.any(np.abs(m_pre_eoc) > abs(M_eoc_Nmm)))

    return SimplifiedMKParts(
        section=section,
        n=n,
        kappa_0=kappa_0,
        kappa_cr=kappa_cr,
        kappa_eoc=kappa_eoc,
        kappa_u=kappa_u,
        M_cr_Nmm=M_cr_Nmm,
        M_eoc_Nmm=M_eoc_Nmm,
        M_u_Nmm=M_u_Nmm,
        kappa_extra_cr_eoc=kappa_extra_cr_eoc,
        M_extra_cr_eoc_Nmm=M_extra_cr_eoc_Nmm,
        kappa_extra_eoc_u=kappa_extra_eoc_u,
        M_extra_eoc_u_Nmm=M_extra_eoc_u_Nmm,
        kappa_yield=kappa_yield,
        M_yield_Nmm=M_yield_Nmm,
        softening_detected=softening_detected,
        softening_extras_applied=False,
    )


def _add_softening_extras_to_simplified_mk_parts(
        parts: SimplifiedMKParts,
        simplification_softening,
        *,
        debug: bool = False,
) -> SimplifiedMKParts:
    """Splice softening extras into existing simplified M-κ parts (in place)."""
    if parts.softening_extras_applied:
        return parts
    if simplification_softening is None:
        return parts

    kappa_soft_cr_eoc, kappa_soft_eoc_u = _parse_simplification_extras(
        simplification_softening,
        parts.kappa_cr,
        parts.kappa_eoc,
        parts.kappa_u,
        param_name="simplification_softening",
    )

    def _moments_at(kappa_arr: np.ndarray):
        if kappa_arr.size == 0:
            return np.array([], dtype=float)
        return np.asarray(
            parts.section.section_calculator.calculate_moment_curvature(
                n=parts.n, chi=kappa_arr
            ).m_y,
            dtype=float,
        )

    M_soft_cr_eoc_Nmm = _moments_at(kappa_soft_cr_eoc)
    M_soft_eoc_u_Nmm = _moments_at(kappa_soft_eoc_u)

    if kappa_soft_cr_eoc.size > 0:
        parts.kappa_extra_cr_eoc = np.concatenate(
            [parts.kappa_extra_cr_eoc, kappa_soft_cr_eoc]
        )
        parts.M_extra_cr_eoc_Nmm = np.concatenate(
            [parts.M_extra_cr_eoc_Nmm, M_soft_cr_eoc_Nmm]
        )
        direction = np.sign(parts.kappa_eoc - parts.kappa_cr) or 1.0
        order = np.argsort(direction * (parts.kappa_extra_cr_eoc - parts.kappa_cr))
        parts.kappa_extra_cr_eoc = parts.kappa_extra_cr_eoc[order]
        parts.M_extra_cr_eoc_Nmm = parts.M_extra_cr_eoc_Nmm[order]

    if kappa_soft_eoc_u.size > 0:
        parts.kappa_extra_eoc_u = np.concatenate(
            [parts.kappa_extra_eoc_u, kappa_soft_eoc_u]
        )
        parts.M_extra_eoc_u_Nmm = np.concatenate(
            [parts.M_extra_eoc_u_Nmm, M_soft_eoc_u_Nmm]
        )
        direction = np.sign(parts.kappa_u - parts.kappa_eoc) or 1.0
        order = np.argsort(direction * (parts.kappa_extra_eoc_u - parts.kappa_eoc))
        parts.kappa_extra_eoc_u = parts.kappa_extra_eoc_u[order]
        parts.M_extra_eoc_u_Nmm = parts.M_extra_eoc_u_Nmm[order]

    parts.softening_extras_applied = True
    if debug:
        print(
            f"[softening] spliced extras: "
            f"added {kappa_soft_cr_eoc.size} cr-EOC + {kappa_soft_eoc_u.size} EOC-u"
        )
    return parts


def _assemble_simplified_mk_results(parts: SimplifiedMKParts) -> MomentCurvatureResults:
    """Assemble MomentCurvatureResults from simplified M-κ parts."""
    moments = np.concatenate(
        (
            np.array([0.0, parts.M_cr_Nmm]),
            parts.M_extra_cr_eoc_Nmm,
            [parts.M_eoc_Nmm],
            parts.M_extra_eoc_u_Nmm,
            parts.M_yield_Nmm,
            [parts.M_u_Nmm],
        )
    )
    curvatures = np.concatenate(
        (
            np.array([parts.kappa_0, parts.kappa_cr]),
            parts.kappa_extra_cr_eoc,
            [parts.kappa_eoc],
            parts.kappa_extra_eoc_u,
            parts.kappa_yield,
            [parts.kappa_u],
        )
    )
    mk_results = parts.section.section_calculator.calculate_moment_curvature(
        n=parts.n, chi=[]
    )
    mk_results.m_y = moments
    mk_results.chi_y = curvatures
    return mk_results


def _print_simplified_mk_debug_table(
        parts: SimplifiedMKParts,
        mk_results: MomentCurvatureResults,
) -> None:
    """Print a readable summary of simplified M-κ keypoints."""
    header = f"{'Point':<25} {'Moment [kNm]':>15} {'Curvature [1/m]':>18}"
    separator = "-" * len(header)
    rows = [
        ("Prestress", mk_results.m_y[0], mk_results.chi_y[0] * 1000),
        ("Cracking", mk_results.m_y[1], mk_results.chi_y[1] * 1000),
    ]
    for i, (M, kappa) in enumerate(
        zip(parts.M_extra_cr_eoc_Nmm, parts.kappa_extra_cr_eoc * 1000)
    ):
        rows.append((f"Extra cr-EOC {i + 1}", M, kappa))
    rows.append(("End of Cracking", parts.M_eoc_Nmm, parts.kappa_eoc * 1000))
    for i, (M, kappa) in enumerate(
        zip(parts.M_extra_eoc_u_Nmm, parts.kappa_extra_eoc_u * 1000)
    ):
        rows.append((f"Extra EOC-u {i + 1}", M, kappa))
    rows.append(("Ultimate", parts.M_u_Nmm, parts.kappa_u * 1000))
    print(separator)
    print(header)
    print(separator)
    for name, M, kappa in rows:
        print(f"{name:<25} {M / 1e6:>15.2f} {kappa:>18.6f}")
    print(separator)


def _calculate_section_state_from_bottom_strain_sls(
        section: BeamSection,
        eps_bot: float,
        n: float = 0.0,
        method: str = "brentq",
        bracket: tuple[float, float] | None = None,
        chi_scan_range: float = 1e-3,
        num_scan_points: int = 100,
        tolerance: float = 1e-1,
        ITMAX: int = 100,
        debug: bool = False,
) -> dict:
    """Compute the SLS section state for a prescribed bottom-fiber strain.

    Fixes the bottom-fiber strain to ``eps_bot`` and finds ``chi_y`` via
    bisection such that the integrated axial force equals ``n``. ``My`` and
    ``Mz`` are outputs. Of all bracketed equilibria, the one with the
    largest ``|My|`` is returned.

    Strain profile convention (consistent with the rest of the codebase):
    ``eps(z) = eps_0 + chi_y * z`` and
    ``eps_bot = eps_0 + chi_y * zmin``  →  ``eps_0 = eps_bot - chi_y * zmin``.

    Parameters
    ----------
    section : BeamSection
        Already-built **SLS** section (e.g. TENSTIFF). Analysed in place;
        no ``sls_section_EC`` / ``deepcopy``. Reuses the section calculator's
        ``integration_data`` if already warmed by earlier SLS M-κ stages.
    eps_bot : float
        Prescribed bottom-fiber strain [-] (positive = tension).
    n : float, optional
        Applied axial force [N] (positive = tension, negative =
        compression). Default: ``0.0``.
    method : str, optional
        ``"brentq"`` (requires ``bracket``) or ``"scan_bisection"``.
        Default: ``"brentq"``.
    bracket : tuple of float or None, optional
        Curvature bracket ``(chi_a, chi_b)`` for ``method='brentq'``.
    chi_scan_range : float, optional
        Half-range for the initial curvature scan [1/mm] when
        ``method='scan_bisection'``. Default: ``1e-3``.
    num_scan_points : int, optional
        Number of scan points for bracketing. Default: ``100``.
    tolerance : float, optional
        Force-imbalance tolerance [N] for the bisection. Default: ``1e-1``.
    ITMAX : int, optional
        Maximum number of bisection iterations. Default: ``100``.
    debug : bool, optional
        If ``True``, print intermediate values. Default: ``False``.

    Returns
    -------
    dict or None
        ``None`` if no equilibrium is bracketed in the scan range.
        On the no-crossing branch, a dict with the keys:

        - ``valid`` : bool — ``False``.
        - ``reason`` : str — explanation, suggesting a larger
          ``chi_scan_range``.

        On success, a dict with the keys:

        - ``valid`` : bool — ``True``.
        - ``n`` : float — integrated axial force [N].
        - ``m_y`` : float — integrated bending moment My [Nmm].
        - ``m_z`` : float — integrated bending moment Mz [Nmm].
        - ``strain_profile`` : list — ``[eps_0, chi_y, 0.0]``.
        - ``section`` : BeamSection — the input SLS ``section``.
    """
    _, _, zmin, zmax = section.geometry.calculate_extents()
    calculator = section.section_calculator

    if debug:
        print("[calculate_curvature_from_bottom_strain]")
        print(f"  eps_bot = {eps_bot * 1000:.4f}‰  |  n = {n:.1f} N")
        print(f"  zmin = {zmin:.2f} mm  |  zmax = {zmax:.2f} mm")

    def get_strain_profile(chi_y: float) -> list:
        eps_0 = eps_bot - chi_y * zmin
        return [eps_0, chi_y, 0.0]

    def get_forces(chi_y: float):
        # Uses calculator.integrate_strain_profile so existing triangulation
        # on this SLS section is reused and persisted.
        forces = calculator.integrate_strain_profile(
            get_strain_profile(chi_y),
            integrate="stress",
        )
        return forces.n, forces.m_y, forces.m_z

    def finalize_result(chi_y: float) -> dict:
        n_final_n, my_final_nmm, mz_final_nmm = get_forces(chi_y)
        residual = n_final_n - n
        if abs(residual) > tolerance:
            warnings.warn(
                f"EOC {method!r} residual {residual:.6g} N exceeds "
                f"tolerance {tolerance:.6g} N.",
                RuntimeWarning,
                stacklevel=2,
            )
        return {
            "valid": True,
            "n": n_final_n,
            "m_y": my_final_nmm,
            "m_z": mz_final_nmm,
            "strain_profile": get_strain_profile(chi_y),
            "section": section,
            "n_residual": residual,
        }

    if method == "brentq":
        if bracket is None:
            raise ValueError("method='brentq' requires a curvature bracket.")

        chi_a, chi_b = sorted((float(bracket[0]), float(bracket[1])))
        dn_a = get_forces(chi_a)[0] - n
        dn_b = get_forces(chi_b)[0] - n
        if dn_a * dn_b > 0.0:
            raise ValueError(
                f"EOC brentq bracket has no sign change: "
                f"f({chi_a:.6e})={dn_a:.6g}, f({chi_b:.6e})={dn_b:.6g}."
            )

        slope = abs((dn_b - dn_a) / (chi_b - chi_a)) if chi_a != chi_b else 0.0
        xtol = max(tolerance / slope, 1e-14) if slope > 0.0 else 1e-14
        chi_final = brentq(
            lambda chi: get_forces(chi)[0] - n,
            chi_a,
            chi_b,
            xtol=xtol,
            rtol=1e-12,
            maxiter=ITMAX,
        )
        return finalize_result(chi_final)

    if method != "scan_bisection":
        raise ValueError(f"Unknown EOC solver method: {method!r}")

    chi_scan = np.linspace(-chi_scan_range, chi_scan_range, num_scan_points)
    dn_scan = np.array([get_forces(chi)[0] - n for chi in chi_scan])

    crossings = [i for i in range(len(dn_scan) - 1) if dn_scan[i] * dn_scan[i + 1] < 0]

    if debug:
        print(f"  Scan found {len(crossings)} zero crossing(s) of (N_int - n)")

    if not crossings:
        return {
            "valid": False,
            "reason": (
                f"No equilibrium found in scan range "
                f"[{-chi_scan_range:.2e}, {chi_scan_range:.2e}] 1/mm. "
                f"Try increasing chi_scan_range."
            ),
        }

    best_result = None
    best_abs_my = -1.0

    for idx in crossings:
        chi_a, chi_b = chi_scan[idx], chi_scan[idx + 1]
        dn_a, dn_b = dn_scan[idx], dn_scan[idx + 1]

        for _ in range(ITMAX):
            if abs(dn_a - dn_b) < tolerance:
                break
            chi_c = (chi_a + chi_b) / 2.0
            N_c, _, _ = get_forces(chi_c)
            dn_c = N_c - n
            if dn_c * dn_a < 0:
                chi_b, dn_b = chi_c, dn_c
            else:
                chi_a, dn_a = chi_c, dn_c

        chi_final = (chi_a + chi_b) / 2.0
        N_final_N, My_final_Nmm, Mz_final_Nmm = get_forces(chi_final)
        sp = get_strain_profile(chi_final)

        if abs(My_final_Nmm) > best_abs_my:
            best_abs_my = abs(My_final_Nmm)
            residual = N_final_N - n
            if abs(residual) > tolerance:
                warnings.warn(
                    f"EOC scan_bisection residual {residual:.6g} N exceeds "
                    f"tolerance {tolerance:.6g} N.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            best_result = {
                "valid": True,
                "n": N_final_N,
                "m_y": My_final_Nmm,
                "m_z": Mz_final_Nmm,
                "strain_profile": sp,
                "section": section,
                "n_residual": residual,
            }

    if debug and best_result:
        chi_y_dbg = best_result["strain_profile"][1]
        eps_0_dbg = best_result["strain_profile"][0]
        eps_top_dbg = eps_0_dbg + chi_y_dbg * zmax
        print(f"  → chi_y = {chi_y_dbg:.6e} 1/mm")
        print(f"  → eps_top = {eps_top_dbg * 1000:.4f}‰")
        print(f"  → My = {best_result['m_y'] / 1e6:.3f} kNm")
        print(f"  → N residual = {best_result['n'] - n:.4f} N")

    return best_result


def calculate_prestress_forces_Nmm(section: BeamSection) -> tuple[float, float]:
    """Calculate the prestressing moment and total prestress force.

    For each prestressed reinforcement the prestressing force is
    ``F_p = A_s * eps_ini * E_s`` and the prestressing moment is
    ``M_p = F_p * z_s`` about the section centroid.

    Parameters
    ----------
    section : BeamSection
        SLS section with prestressed reinforcement.

    Returns
    -------
    tuple of float
        ``(M_p, N_p)`` where ``M_p`` is the prestressing moment [Nmm]
        (always positive) and ``N_p`` is the total prestress force [N].
    """
    # Get section centroid
    cz = section.gross_properties.cz

    # Initialize Forces
    M_p = 0.0 # [Nmm]
    N_p = 0.0 # [N]

    # Get prestressed reinforcement point geometries
    if hasattr(section.geometry, 'point_geometries'):
        for pg in section.geometry.point_geometries:
            # Get reinforcement material
            reinf = pg.material

            # Check if reinforcement is prestressed
            if hasattr(reinf, 'initial_strain') and reinf.initial_strain is not None:
                eps_ini = reinf.initial_strain  # Initial strain from prestress

                # Skip if no prestress
                if abs(eps_ini) < 1e-10:
                    continue

                # Reinforcement properties
                E_s = reinf.Es  # MPa
                A_s = pg.area  # mm²
                z_s = pg.point.y  # z-coordinate (mm)

                # Prestressing force: F_p = A_s × eps_ini × E_s
                F_p = A_s * eps_ini * E_s  # N

                # Moment arm from centroid
                d = z_s - cz  # mm

                # Add contribution to total prestressing moment
                M_p += F_p * d

                # Add contribution to total prestress normal force
                N_p += F_p

    return abs(M_p), N_p


def _ensure_integration_data(section: BeamSection) -> list:
    """Return triangulation data, computing it once if needed."""
    calculator = section.section_calculator
    integration_data = getattr(calculator, "integration_data", None)
    if integration_data is None:
        mesh_size = getattr(calculator, "mesh_size", 0.01)
        integration_data = calculator.integrator.triangulate(
            section.geometry, mesh_size
        )
        calculator.integration_data = integration_data
    return integration_data


def _integrate_stress_and_modulus_at_strain(
        section: BeamSection,
        strain: np.ndarray | list[float],
) -> tuple[np.ndarray, np.ndarray]:
    """One-pass fiber integrate of stress resultants and tangent stiffness.

    Uses the same strain convention as structuralcodes fiber integration:
    ``eps = eps_a - kappa_z * y + kappa_y * z``.
    """
    integration_data = _ensure_integration_data(section)
    eps_a, kappa_y, kappa_z = (float(v) for v in strain)

    y_parts: list[np.ndarray] = []
    z_parts: list[np.ndarray] = []
    force_parts: list[np.ndarray] = []
    modulus_parts: list[np.ndarray] = []

    for y, z, area, law in integration_data:
        strains = eps_a - kappa_z * y + kappa_y * z
        stress = np.asarray(law.get_stress(strains), dtype=float)
        tangent = np.asarray(law.get_tangent(strains), dtype=float)
        y_parts.append(np.asarray(y, dtype=float))
        z_parts.append(np.asarray(z, dtype=float))
        force_parts.append(stress * area)
        modulus_parts.append(tangent * area)

    y_all = np.hstack(y_parts)
    z_all = np.hstack(z_parts)
    forces = np.hstack(force_parts)
    ma = np.hstack(modulus_parts)

    response = np.array(
        [np.sum(forces), np.sum(forces * z_all), np.sum(-forces * y_all)],
        dtype=float,
    )
    stiffness = np.zeros((3, 3), dtype=float)
    stiffness[0, 0] = np.sum(ma)
    stiffness[0, 1] = stiffness[1, 0] = np.sum(ma * z_all)
    stiffness[0, 2] = stiffness[2, 0] = np.sum(-ma * y_all)
    stiffness[1, 1] = np.sum(z_all * z_all * ma)
    stiffness[1, 2] = stiffness[2, 1] = np.sum(-y_all * z_all * ma)
    stiffness[2, 2] = np.sum(y_all * y_all * ma)
    return response, stiffness


def _stiffness_from_gross_properties(section: BeamSection) -> np.ndarray:
    """Build the zero-strain section stiffness matrix from gross properties.

    Matches the fiber-integrator layout about the global origin:

    ``K = [[ea, e_sy, -e_sz], [e_sy, e_iyy, -e_iyz], [-e_sz, -e_iyz, e_izz]]``.
    """
    gp = section.gross_properties
    return np.array(
        [
            [gp.ea, gp.e_sy, -gp.e_sz],
            [gp.e_sy, gp.e_iyy, -gp.e_iyz],
            [-gp.e_sz, -gp.e_iyz, gp.e_izz],
        ],
        dtype=float,
    )


def _calculate_kappa_0(
    sls_sec: BeamSection,
    n: float = 0.0,
    *,
    method: str = "two_pass",
    debug: bool = False,
) -> float:
    """Compute the initial curvature κ₀ for prestressed sections.

    Used by both the full and simplified M-κ paths in
    :func:`calculate_moment_curvature_sls_EC`.

    Method (initial tangent stiffness)
    ----------------------------------
    Prestress is already embedded in the reinforcement material via
    ``initial_strain``. At zero generalized strain
    ``[eps_a, chi_y, chi_z] = [0, 0, 0]``, the section therefore carries a
    residual prestress force vector

        response_0 = [N_0, M_y0, M_z0].

    The corresponding uncracked elastic initial state under external loads
    ``target = [n, 0, 0]`` (external axial force ``n``, no external moments)
    is the single linear solve

        response_0 + K_0 · delta_strain = target

    where ``K_0`` is the section tangent stiffness matrix at zero strain
    (composite concrete + reinforcement). The curvature component of
    ``delta_strain`` is κ₀:

        kappa_0 = delta_strain[1]

    This is non-iterative and stays on the initial elastic branch; it does
    not probe the M-κ diagram or extrapolate from two curvature points.

    If the section is not prestressed (``M_p = 0``), returns ``0.0``.

    Parameters
    ----------
    sls_sec : BeamSection
        Section to analyse (assumed SLS section).
    n : float, optional
        External axial force [N] (positive = tension). Default: ``0.0``.
    method : {"two_pass", "combined", "gross_k"}, optional
        How ``response_0`` / ``K_0`` are obtained:

        - ``"two_pass"`` — production default: separate stress and modulus
          fiber integrates via structuralcodes.
        - ``"combined"`` — one local fiber pass computing both (method B).
        - ``"gross_k"`` — stress fiber integrate for ``response_0``,
          ``K_0`` from :attr:`BeamSection.gross_properties` (method C).

        Default: ``"two_pass"``.
    debug : bool, optional
        Print intermediate values. Default: ``False``.

    Returns
    -------
    float
        Initial curvature κ₀ [1/mm].

    Raises
    ------
    numpy.linalg.LinAlgError
        If the initial tangent stiffness matrix ``K_0`` is singular.
    ValueError
        If ``method`` is unknown.
    """
    M_p_Nmm, _ = calculate_prestress_forces_Nmm(sls_sec)
    if M_p_Nmm == 0:
        return 0.0

    target = np.array([n, 0.0, 0.0], dtype=float)
    zero_strain = np.zeros(3, dtype=float)
    calculator = sls_sec.section_calculator

    if method == "two_pass":
        response_0 = calculator.integrate_strain_profile(
            zero_strain,
            integrate="stress",
        ).asarray()
        stiffness_0 = calculator.integrate_strain_profile(
            zero_strain,
            integrate="modulus",
        ).asarray()
    elif method == "combined":
        response_0, stiffness_0 = _integrate_stress_and_modulus_at_strain(
            sls_sec, zero_strain
        )
    elif method == "gross_k":
        response_0 = calculator.integrate_strain_profile(
            zero_strain,
            integrate="stress",
        ).asarray()
        stiffness_0 = _stiffness_from_gross_properties(sls_sec)
    else:
        raise ValueError(
            "method must be 'two_pass', 'combined', or 'gross_k', "
            f"got {method!r}"
        )

    delta_strain = np.linalg.solve(stiffness_0, target - response_0)
    kappa_0 = float(delta_strain[1])

    if debug:
        residual = response_0 + stiffness_0 @ delta_strain - target
        print(
            f"[kappa_0 method={method}]: "
            f"response_0={response_0}  "
            f"delta_strain={delta_strain}  "
            f"residual={residual}  "
            f"→ κ₀={kappa_0 * 1000:.6f} 1/m"
        )

    return kappa_0


def get_strain_at_point(strain_profile, y, z) -> float:
    """Compute the strain at point (y, z) for a given strain profile.

    Evaluates ``eps_0 + chi_y * z + chi_z * y``.

    Parameters
    ----------
    strain_profile : list
        ``[eps_0, chi_y, chi_z]`` with axial strain [-] and curvatures
        [1/mm].
    y : float
        y-coordinate [mm].
    z : float
        z-coordinate [mm].

    Returns
    -------
    float
        Strain at point (y, z) [-].
    """
    eps_0, chi_y, chi_z = strain_profile
    return eps_0 + chi_y * z + chi_z * y

def sls_section_EC(
        section: BeamSection,
        constitutive_law: str,
) -> BeamSection:
    """Return the section with an SLS constitutive law for the concrete.

    Parameters
    ----------
    section : BeamSection
        Section to convert (SLS or ULS).
    constitutive_law : str
        Keyword for the constitutive law (see ``create_sls_concrete_EC()``
        for available keywords).

    Returns
    -------
    BeamSection
        New section with the SLS concrete material; reinforcement unchanged.
    """
    # Get the geometry of the section
    geo = section.geometry

    # Create SLS Concrete from Concrete Used in Section
    conc = get_concrete(section)
    sls_conc = create_sls_concrete_EC(conc, constitutive_law)

    # Change Concrete Material
    processed_geoms = []
    for g in geo.geometries:
        processed_geoms.append(
            SurfaceGeometry.from_geometry(geo=g, new_material=sls_conc) # change concrete material
        )
    for pg in geo.point_geometries:
        processed_geoms.append(pg) # keep same reinforcement material

    from integrator_util import section_integrator

    new_sls_section = BeamSection(
        CompoundGeometry(geometries=processed_geoms),
        name=section.name,
        integrator=section_integrator(),
        mesh_size=0.01,
    )

    return new_sls_section

def flipped_section(section: BeamSection) -> BeamSection:
    """Return the section rotated by 180°, for support bending strength.

    Used when calculating the bending strength at a support, where the
    section is effectively flipped.

    Parameters
    ----------
    section : BeamSection
        Section to flip.

    Returns
    -------
    BeamSection
        The section rotated 180° about its centroid, named
        ``"<name> (Support)"``.
    """
    geometry = section.geometry

    gross_props = section.gross_properties

    centroid = (gross_props.cy, gross_props.cz)

    flipped_support_section_geometry = geometry.rotate(
        angle=180,
        point=centroid,
        use_radians=False)

    from integrator_util import section_integrator

    rotated_section = BeamSection(
        flipped_support_section_geometry,
        name=f"{section.name} (Support)",
        integrator=section_integrator(),
        mesh_size=0.01,
    )

    return rotated_section

def get_concrete(section: BeamSection) -> Concrete:
    """Return the first concrete material found in the section geometry.

    Parameters
    ----------
    section : BeamSection
        Section to query.

    Returns
    -------
    Concrete
        The first concrete material in the geometry.
    """
    # For CompoundGeometry, get material from the first surface geometry
    geometry = section.geometry
    if hasattr(geometry, 'geometries'):
        # CompoundGeometry - get concrete from first surface
        concrete = geometry.geometries[0].material
    else:
        # Simple SurfaceGeometry
        concrete = geometry.material

    return concrete

def get_reinforcement(section: BeamSection) -> tuple[Reinforcement, float]:
    """Return the first reinforcement material and its area.

    Assumes all reinforcement diameters are the same.

    Parameters
    ----------
    section : BeamSection
        Section to query.

    Returns
    -------
    tuple
        ``(reinforcement, area)`` where ``reinforcement`` is the first
        :class:`Reinforcement` material and ``area`` is the corresponding
        bar area [mm²].

    Raises
    ------
    ValueError
        If the geometry contains no reinforcement points, or no
        reinforcement material is found.
    """

    geometry = section.geometry

    # simple surface / not compound? then nothing to check
    if not hasattr(geometry, "geometries"):
        raise ValueError("Geometry does not contain reinforcement points.")

    # compound → scan point geometries
    if hasattr(geometry, "point_geometries"):
        for geo in geometry.point_geometries:
            mat = getattr(geo, "material", None)
            area = (geo.diameter ** 2 / 4) * np.pi
            if isinstance(mat, Reinforcement):
                return mat, area

    raise ValueError("No reinforcement material found in section geometry.")

"""
HP-slab analysis function for HpDesignBench.

Builds the full slab construction object from a decoded parameter
dictionary, evaluates all structural, construction, acoustic, and
modeling checks, computes the weighted objective function, and returns
a result dictionary compatible with the IOH benchmarking framework.

Framework adapted from: Max Dombrowski

Scope of checks and penalized penalty function formulation adapted
from Jamila Loutfi :cite:`loutfi_2023`

Author: Elliot Melcer
"""
from structuralcodes import set_design_code
from structuralcodes.materials.concrete import create_concrete

from core.analysis_core.checks.acoustic_checks import AirborneSoundInsulationCheck, ImpactSoundInsulationCheck
from core.analysis_core.checks.construction_checks import MidlineConcreteCoverCheck, ReinforcementSpacingCheck, \
    MinimumHPShellThicknessCheck
from core.analysis_core.checks.modeling_checks import NtDyCombinationCheck, BeamTheoryHgesLRatioCheck, \
    BeamTheoryBLRatioCheck
from core.analysis_core.checks.structural_checks import UltimateMomentCheckEC2004DE, \
    DeflectionLimitByDeflectionCheckEC2004DE, DeflectionLimitByMcrCheckEC2004DE, \
    FailureAnnouncementByDeflectionCheckEC2004DE, FailureAnnouncementByMcrCheckEC2004DE
from core.analysis_core.section_methods import InvalidSectionForMKError, prepare_deflection_mk_cache, \
    prepare_reference_analysis_cache_EC
from core.analysis_core.statics.constants import SystemType, MomentType
from core.analysis_core.statics.loads import LoadsEC
from core.analysis_core.material_methods import get_cube_EC, get_cfrp_reinforcement_from_registry, \
    get_floor_material_from_registry
from core.ioh_core.io_util import _req_param
from core.unit_core import mm3_to_m3
from slab_construction.slab_construction import SlabConstruction
from slab_construction.floor import FloorLayer, Floor
from slab_construction.slabs.hp_slab.hp_model.hp_geometry import HPGeometry
from slab_construction.slabs.hp_slab.hp_model.hp_shell import HPShell
from slab_construction.slabs.hp_slab.hp_model.hp_slab import HPSlab


def resolve_active_constraints(params: dict, constraints: dict) -> dict:
    """
    Filter the constraint dictionary based on the fixed SLS deflection case.

    Called once per problem build (before IOH registration) with the
    fixed parameters of that problem. Removes the checks that are
    mutually exclusive with the chosen deflection case so that the IOH
    logger only tracks the relevant constraints.

    Parameters
    ----------
    params : dict
        Fixed parameter dictionary for the problem being built. Must
        contain the key ``"defl_sls_case"`` with value ``"a"`` or
        ``"b"`` (case-insensitive).
    constraints : dict
        Full constraint configuration dict as returned by
        :func:`load_problems_combined`.

    Returns
    -------
    dict
        Filtered copy of ``constraints`` with mutually exclusive checks
        removed:

        - Case ``"a"``: removes ``B1b_deflection_by_mcr_capacity`` and
          ``B2b_failure_announcement_by_mcr_capacity``.
        - Case ``"b"``: removes ``B1a_deflection_by_wmax_capacity`` and
          ``B2a_failure_announcement_by_wmin_capacity``.
        - Any other value: returns ``constraints`` unchanged.
    """
    out = dict(constraints)
    case = (params.get("defl_sls_case") or "").strip().lower()
    if case == "a":
        out.pop("B1b_deflection_by_mcr_capacity", None)
        out.pop("B2b_failure_announcement_by_mcr_capacity", None)
    elif case == "b":
        out.pop("B1a_deflection_by_wmax_capacity", None)
        out.pop("B2a_failure_announcement_by_wmin_capacity", None)
    return out


def analysis(params: dict, constraints: dict, materials: dict, debug: bool = False) -> dict:
    """
    Run the full HP-slab analysis for a single candidate design.

    Builds the HP-slab construction object from decoded parameters,
    evaluates all structural (A), serviceability (B), construction (C),
    acoustic (D), and modeling (Z) checks, computes the weighted
    objective function, applies the multiplicative penalty per Loutfi :cite:`loutfi_2023`.
    Finally, it returns all results in a format compatible with the
    :class:`EvalContext` cache.

    All parameters in params : dict must be defined inside the
    .csv-files within the hp_slab package

    Parameters
    ----------
    params : dict
        Decoded parameter dictionary as returned by ``decode(x_idx)``.
        Required keys (extracted via :func:`_req_param`):

        *Geometry:* ``geom_span_mm``, ``geom_b_mm``, ``geom_h_ges_mm``,
        ``geom_t_mm``, ``geom_nt``, ``geom_dy_mm``,
        ``geom_hx_hges_ratio``,
        ``geom_t_infill_mm``, ``geom_t_insulation_mm``,
        ``geom_t_screed_mm``.

        *Materials:* ``mat_conc_fck``, ``mat_reinf_id``,
        ``reinf_a_tex_mm2``, ``reinf_kap_t_percent``,
        ``mat_infill_id``, ``mat_insu_id``, ``mat_screed_id``,
        ``mat_conc_cost_eur_m3``, ``mat_conc_gwp_kgco2e_m3``,
         ``mat_conc_cost_c30_ref_eur_m3``, ``mat_conc_gwp_c30_ref_kgco2e_m3``,
        ``mat_reinf_cost_crfp/conc``, ``mat_reinf_gwp_crfp/conc``.

        *Loads:* ``loads_N_kN``, ``loads_category``.

        *Deflection:* ``defl_max_defl_limit``,
        ``defl_max_announce_failure``, ``defl_sls_case``.

        *Acoustics:* ``insu_mod_damp``, ``insu_rw_req_db``,
        ``insu_lnw_max_db``.

        *Beam theory:* ``f_beam_theory``.

        *Objective weights:* ``weight_omega_1_gwp``, ``weight_omega_2_cost``.

    constraints : dict
        Active constraint configuration dict for this problem, as
        returned by :func:`resolve_active_constraints`. Each entry maps
        a constraint name to its config dict (must contain
        ``"active"``).
    materials : dict
        Materials registry dict as returned by
        :func:`load_materials_registry`.
    debug : bool, optional
        If ``True``, prints detailed constraint values, penalty values,
        and penalty product to console. Default is ``False``.

    Returns
    -------
    dict
        Result dictionary with the following keys:

        - ``"y"`` — unpenalized objective value (weighted cost + GWP) [€ or kg CO₂-eq or combined, depending on weights].
        - ``"y_p"`` — penalized objective value [€ or kg CO₂-eq or combined, depending on weights]..
        - ``"constraint_values"`` — dict of all computed utilization ratios [-].
        - ``"penalties_"`` — dict of active penalty factors (1.0 if
          satisfied, utilization value if > 1.0) [-].
        - ``"params"`` — copy of the input ``params`` dict.
        - ``"feasible"`` — ``True`` (always set; feasibility is implied
          by ``y_p == y``).
        - ``"analysis_error"`` — ``None`` (or error info if material
          creation fails; in that case ``"y"`` and ``"y_p"`` are
          ``float("inf")``).

    Notes
    -----
    **Objective function:**

    .. math::

        y = \\Omega_2 \\cdot y_{\\text{cost}} + \\Omega_1 \\cdot y_{\\text{gwp}}

    where :math:`y_{\\text{cost}}` and :math:`y_{\\text{gwp}}` are the
    material cost and global warming potential of the concrete shell and
    CFRP reinforcement, respectively. Reinforcement cost and GWP are
    expressed as factors relative to C30/37 reference concrete.

    **Penalty formulation:**

    All constraint utilization ratios u_i ≥ 0 are collected. For active
    constraints the penalty factor is 1.0 if u_i ≤ 1.0 and u_i otherwise.
    The penalized objective is:

    .. math::

        y_p = y \\cdot \\prod_{i} p_i^2

    **SLS deflection case:**

    Checks B.1 and B.2 exist in two variants (a: deflection-based,
    b: M_{cr}-based); the active pair is selected by ``defl_sls_case``
    and the inactive pair is excluded from the penalty product.

    **Acoustic buffers:**

    A safety buffer of 2 dB is applied to the airborne sound check (D.1)
    and 3 dB to the impact sound check (D.2).
    """

    # ======================================================
    # EXTRACT PARAMETERS
    # ======================================================

    # Geometry
    span_mm     = _req_param(params, "geom_span_mm")
    B_mm        = _req_param(params, "geom_b_mm")
    h_ges_mm    = _req_param(params, "geom_h_ges_mm")
    t_mm        = _req_param(params, "geom_t_mm")
    nt          = int(_req_param(params, "geom_nt"))
    dy_mm       = _req_param(params, "geom_dy_mm")
    hx_hges_ratio = _req_param(params, "geom_hx_hges_ratio")

    # Concrete
    conc_fck_MPa = _req_param(params, "mat_conc_fck")

    # Reinforcement
    reinf_id = params.get("mat_reinf_id", "")

    reinf_area_mm2 = _req_param(params, "reinf_a_tex_mm2")
    prestress_pct = _req_param(params, "reinf_kap_t_percent")

    # Floor Materials
    infill_id = params.get("mat_infill_id", "")
    insu_id = params.get("mat_insu_id", "")
    screed_id = params.get("mat_screed_id", "")

    infill_t_mm = _req_param(params, "geom_t_infill_mm")
    insu_t_mm = _req_param(params, "geom_t_insulation_mm")
    screed_t_mm = _req_param(params, "geom_t_screed_mm")

    # Loads
    n = _req_param(params,"loads_N_kN")
    load_category = params.get("loads_category", "")

    # Deformations
    defl_limit_factor_w_max = _req_param(params, "defl_max_defl_limit")
    defl_min_factor_announce_failure = _req_param(params, "defl_max_announce_failure")
    defl_sls_case = params.get("defl_sls_case", "")

    # Acoustic Parameters
    modular_attenuation = _req_param(params, "insu_mod_damp")
    R_w_req_db = _req_param(params, "insu_rw_req_db")
    L_nw_max_db = _req_param(params, "insu_lnw_max_db")

    # Beam Theory
    f_beam_theory = _req_param(params, "f_beam_theory")

    # ======================================================================================================================
    # CREATE MATERIALS
    # ======================================================================================================================
    set_design_code('ec2_2004')

    # Concrete

    concrete_uls = create_concrete(
        fck=conc_fck_MPa,
        constitutive_law ='parabolarectangle',
        alpha_cc = 0.85,
        gamma_c = 1.5,
        name = f"C {conc_fck_MPa}/{get_cube_EC(conc_fck_MPa)} ULS")

    # Reinforcement
    try:
        reinforcement = get_cfrp_reinforcement_from_registry(
            mat_id=reinf_id,
            materials=materials,
            prestress_percent=prestress_pct,
            gamma_s=1.3
        )
    except (KeyError, ValueError) as e:
        print(f"Error creating reinforcement: {e}")
        # Return infeasible solution
        return {
            "y": float("inf"),
            "y_p": float("inf"),
            "violations": {"material_error": 1.0},
            "params": params
        }

    # Floor materials
    try:
        infill_material = get_floor_material_from_registry(infill_id, materials)
        insulation_material = get_floor_material_from_registry(insu_id, materials)
        screed_material = get_floor_material_from_registry(screed_id, materials)
    except (KeyError, ValueError) as e:
        print(f"Error creating floor materials: {e}")
        return {
            "y": float("inf"),
            "y_p": float("inf"),
            "violations": {"material_error": 1.0},
            "params": params
        }

    # ======================================================================================================================
    # CREATE FLOOR
    # ======================================================================================================================

    infill_layer            = FloorLayer(infill_material, infill_t_mm)
    sound_insulation_layer  = FloorLayer(insulation_material, insu_t_mm)
    screed_layer            = FloorLayer(screed_material, screed_t_mm)

    floor = Floor([infill_layer, sound_insulation_layer, screed_layer])

    # ======================================================================================================================
    # CREATE HP SLAB
    # ======================================================================================================================

    # Calculate Hx and Hy
    Hx_mm = hx_hges_ratio       * h_ges_mm
    Hy_mm = (1-hx_hges_ratio)   * h_ges_mm

    # HP Geometry
    hp_geom = HPGeometry(
        B=B_mm,
        L=span_mm,
        Hx=Hx_mm,
        Hy=Hy_mm,
        t=t_mm,
        dy=dy_mm,
        nt=nt
    )

    # HP-Shell
    hp_shell = HPShell(hp_geom, concrete_uls, reinforcement, reinf_area = reinf_area_mm2)

    # HP-Slab
    hp_slab = HPSlab(hp_shell, infill_material)

    # HP-Slab Construction
    slab_construction = SlabConstruction(hp_slab, floor)

    # ======================================================================================================================
    # ANALYSIS CACHE — reference sections/ULS M_u + coordinated simplified M-κ
    # (M-κ also stores SLS M_cr for B1b/B2b/ζ)
    # ======================================================================================================================
    cache = slab_construction.analysis_cache
    prepare_reference_analysis_cache_EC(slab_construction, n=n)

    try:
        prepare_deflection_mk_cache(slab_construction, n=n)
    except InvalidSectionForMKError:
        # Infeasible sections are handled by the individual checks.
        cache.mk_curves.clear()
        cache.mk_metadata.clear()


    # ======================================================================================================================
    # LIVE LOADS
    # ======================================================================================================================

    live_loads = LoadsEC.from_categories_EC0_NA_DE(load_category)

    # ======================================================================================================================
    # COMPUTE CONSTRAINTS (A) - ULS
    # ======================================================================================================================

    m_u_A_util = UltimateMomentCheckEC2004DE.calculate_utilization(
        slab_construction = slab_construction,
        loads = live_loads,
        system = SystemType.SIMPLE_BEAM,
        moment = MomentType.MAX_POS_MOMENT,
        n = n)

    # ======================================================================================================================
    # COMPUTE CONSTRAINTS (B) - SLS
    # ======================================================================================================================

    # B.1a Limiting Deflection by Checking the Maximum Deflection against Limit Factor

    w_max_B1a_util = DeflectionLimitByDeflectionCheckEC2004DE.calculate_utilization(
        slab_construction = slab_construction,
        loads = live_loads,
        system = SystemType.SIMPLE_BEAM,
        limit_factor=defl_limit_factor_w_max
    )

    # B.1b Limiting Deflection by Checking the Quasi-Permanent Moment Against the Cracking Moment

    w_max_B1b_util = DeflectionLimitByMcrCheckEC2004DE.calculate_utilization(
        slab_construction = slab_construction,
        loads = live_loads,
        system=SystemType.SIMPLE_BEAM,
        moment=MomentType.MAX_POS_MOMENT,
        n=n,
    )

    # B.2a Check Minimum Deflection under Fundamental Combination

    fa_B2a_util = FailureAnnouncementByDeflectionCheckEC2004DE.calculate_utilization(
        slab_construction = slab_construction,
        loads = live_loads,
        system=SystemType.SIMPLE_BEAM,
        min_factor = defl_min_factor_announce_failure
    )

    # B.2b Limiting Deflection by Checking the Quasi-Permanent Moment Against the Cracking Moment

    fa_B2b_util = FailureAnnouncementByMcrCheckEC2004DE.calculate_utilization(
        slab_construction=slab_construction,
        loads=live_loads,
        system=SystemType.SIMPLE_BEAM,
        moment=MomentType.MAX_POS_MOMENT,
        n=n,
    )

    # ======================================================================================================================
    # COMPUTE CONSTRAINTS (C) - CONSTRUCTION
    # ======================================================================================================================

    # C.1. Sufficient Concrete Cover from the outermost Reinforcement to the Edge along the HP-Shell Midline

    cc_C1_util = MidlineConcreteCoverCheck.calculate_utilization(
        slab_construction=slab_construction,
    )

    # C.2. Check for Sufficient Clear Spacing between Reinforcement along the HP-Shell Midline

    s_C2_util = ReinforcementSpacingCheck.calculate_utilization(
        slab_construction = slab_construction,
    )

    # C.3 Check for Minimum Shell Thickness

    tmin_C3_util = MinimumHPShellThicknessCheck.calculate_utilization(
        slab_construction = slab_construction,
    )

    # ======================================================================================================================
    # COMPUTE CONSTRAINTS (D) - INSULATION
    # ======================================================================================================================

    # D.1 Airborne Sound Insulation Check

    asi_D1_util = AirborneSoundInsulationCheck.calculate_utilization(
        slab_construction = slab_construction,
        limit_dB = R_w_req_db,
        mod_att = modular_attenuation,
        buffer_dB = 2.0
    )

    isi_D2_util = ImpactSoundInsulationCheck.calculate_utilization(
        slab_construction = slab_construction,
        limit_dB = L_nw_max_db,
        mod_att = modular_attenuation,
        buffer_dB = 3.0
    )

    # ======================================================================================================================
    # COMPUTE CONSTRAINTS (Z) - MODELING
    # ======================================================================================================================

    # Z.1. Combination of nt and dy

    ntdy_Z1_util = NtDyCombinationCheck.calculate_utilization(
        slab_construction = slab_construction
    )

    # Z.2. Beam Theory H_ges / L - Ratio

    beam_hL_Z2_util = BeamTheoryHgesLRatioCheck.calculate_utilization(
        slab_construction = slab_construction,
        f_b=f_beam_theory,
    )

    # Z.3. Beam Theory B / L - Ratio

    beam_BL_Z3_util = BeamTheoryBLRatioCheck.calculate_utilization(
        slab_construction = slab_construction,
        f_b=f_beam_theory,
    )

    # ======================================================================================================================
    # COMPUTE WEIGHTED OBJECTIVE VALUE
    # ======================================================================================================================

    # Reference Values for cost and gwp (C30/37)
    cost_conc_c30_ref = _req_param(params, "mat_conc_cost_c30_ref_eur_m3")
    gwp_conc_c30_ref = _req_param(params, "mat_conc_gwp_c30_ref_kgco2e_m3")

    # Cost and GWP Factors for reinforcement based on reference concrete C30/37
    cost_reinf_factor = _req_param(params, "mat_reinf_cost_crfp/conc")
    gwp_reinf_factor = _req_param(params, "mat_reinf_gwp_crfp/conc")

    # Compute Material Quantities
    concrete_m3 = mm3_to_m3(hp_shell.net_concrete_volume())
    reinforcement_m3 = mm3_to_m3(hp_shell.total_reinforcement_volume())

    # Prices in €/m3
    cost_concrete_eur_m3 = _req_param(params, "mat_conc_cost_eur_m3")
    cost_reinforcement_eur_m3 = cost_conc_c30_ref * cost_reinf_factor

    # GWP in CO2eq./m3
    gwp_concrete_CO2eq_m3 = _req_param(params, "mat_conc_gwp_kgco2e_m3")
    gwp_reinforcement_CO2eq_m3 = gwp_conc_c30_ref * gwp_reinf_factor

    # Unpenalized objective function
    y_cost = cost_concrete_eur_m3 * concrete_m3 + cost_reinforcement_eur_m3 * reinforcement_m3
    y_gwp = gwp_concrete_CO2eq_m3 * concrete_m3 + gwp_reinforcement_CO2eq_m3 * reinforcement_m3

    weight_cost = _req_param(params, "weight_omega_2_cost")
    weight_gwp = _req_param(params, "weight_omega_1_gwp")

    y = y_cost * weight_cost + y_gwp * weight_gwp

    # ======================================================================================================================
    # COMPUTE OBJECTIVE FUNCTION
    # Author: Max Dombrowski
    # ======================================================================================================================
    # Collect constraint values

    # A
    constraint_values = {"A_bending_capacity": m_u_A_util}

    # B Constraints According to SLS Case a or b
    if defl_sls_case == "a":
        constraint_values["B1a_deflection_by_wmax_capacity"] = w_max_B1a_util
        constraint_values["B2a_failure_announcement_by_wmin_capacity"] = fa_B2a_util
    else:
        constraint_values["B1b_deflection_by_mcr_capacity"] = w_max_B1b_util
        constraint_values["B2b_failure_announcement_by_mcr_capacity"] = fa_B2b_util

    # C
    constraint_values["C1_concrete_cover_capacity"] = cc_C1_util
    constraint_values["C2_clear_spacing_capacity"] = s_C2_util
    constraint_values["C3_shell_thickness_capacity"] = tmin_C3_util

    # D
    constraint_values["D1_airborne_sound_insulation_capacity"] = asi_D1_util
    constraint_values["D2_impact_sound_insulation_capacity"] = isi_D2_util

    # Z
    constraint_values["Z1_nt_dt_combination_capacity"] = ntdy_Z1_util
    constraint_values["Z2_beam_theory_H_L_capacity"] = beam_hL_Z2_util
    constraint_values["Z3_beam_theory_B_L_capacity"] = beam_BL_Z3_util

    print(
        "constraint values: {"
        + ", ".join(f"'{k}': {v:.3f}" for k, v in constraint_values.items())
        + "}"
    )

    # penalty factors: 1 if satisfied, utilisation value if > 1
    penalties_ = {
        name: (1.0 if value <= 1.0 else float(value))
        for name, value in constraint_values.items()
    }

    print(
        "penalties_: {"
        + ", ".join(f"'{k}': {v:.3f}" for k, v in penalties_.items())
        + "}"
    )

    # compile a list of constraints that are active for this problem to return them
    active_penalties_ = {
        name: penalties_[name]
        for name, meta in constraints.items()
        if meta.get("active", True) and name in penalties_
    }

    # Multiplicative penalty: product of (penalty^2)
    penalty_product_ = 1.0
    for name, v in active_penalties_.items():
        # v >= 1 by construction
        penalty_product_ *= (v ** 2.0)

    y_p = y * penalty_product_
    print(f"penalty product: {penalty_product_:.3f}")
    print(f"penalized objective function: {y_p:.3f} \n")

    if debug:
        # After calculating constraints
        print("\nDEBUG constraint_values:")
        for k, v in constraint_values.items():
            print(f"  {k}: {v} (type: {type(v).__name__}, is_inf: {v == float('inf')})")

        print("\nDEBUG penalties_:")
        for k, v in penalties_.items():
            print(f"  {k}: {v} (type: {type(v).__name__})")

        print(f"\nDEBUG penalty_product_: {penalty_product_} (type: {type(penalty_product_).__name__})")


    # ======================================================================================================================
    # RETURN RESULTS
    # ======================================================================================================================

    return {
        "y": y,
        "y_p": y_p,
        "constraint_values": constraint_values,
        "penalties_": active_penalties_,
        "params": dict(params),
        "feasible": True,
        "analysis_error": None,
    }
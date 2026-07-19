"""
Structural utilization checks for HP-shell slab constructions.
Numbering according to Loutfi :cite:`loutfi_2023`

Covers ultimate limit state (ULS) bending strength and serviceability
limit state (SLS) deflection and cracking checks per EN 1992-1-1:2004/NA(DE) :cite:`ec2`

Adapted from: Jamila Loutfi :cite:`loutfi_2023`
"""
from abc import ABC, abstractmethod

from core.analysis_core.statics.constants import SystemType, MomentType
from core.analysis_core.statics.deflection import DeflectionCalculator
from core.analysis_core.statics.internal_forces import InternalForces
from core.analysis_core.statics.loads import Loads
from core.analysis_core.section_methods import (
    DEFLECTION_MK_SIMPLIFICATION,
    DEFLECTION_MK_SIMPLIFICATION_SOFTENING,
    InvalidSectionForMKError,
)
from core.unit_core import Nmm_to_kNm
from slab_construction.slab_construction import SectionResultKey, SlabConstruction


class StructuralCheck(ABC):
    """
    Abstract base class for structural utilization checks.
    Author: Elliot Melcer

    All StructuralCheck subclasses must implement :meth:`calculate_utilization`,
    which returns a dimensionless utilization ratio where values ≤ 1.0
    indicate a passing design.
    """

    @staticmethod
    @abstractmethod
    def calculate_utilization(
            slab_construction: SlabConstruction,
            loads: Loads,
            system: str,
            moment: str) -> float:
        """
        Compute the structural utilization ratio for a slab construction.

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.
        loads : Loads
            Applied loads object (uniformly distributed over all spans).
        system : str
            Structural system identifier (see :class:`SystemType`).
        moment : str
            Moment type identifier (see :class:`MomentType`).

        Returns
        -------
        float
            Utilization ratio [-]. Values ≤ 1.0 indicate a passing design.
        """
        raise NotImplementedError


"""ULTIMATE LIMIT STATE"""


"""A.1 Ultimate Moment Check"""


class UltimateMomentCheckEC2004DE(StructuralCheck):
    """
    ULS bending strength check per EN 1992-1-1:2004/NA(DE) :cite:`ec2`.

    Computes the utilization ratio |M_Ed| / M_Rd at the cross-section
    position where the governing design moment occurs. For positive
    moments the section is used as-is; for negative moments the section
    is flipped before calling the strength calculation.

    Infeasible sections (no valid equilibrium) are penalized with a
    fixed utilization of ``10.0``.
    """

    @staticmethod
    def calculate_utilization(
            slab_construction: SlabConstruction,
            loads: Loads,
            system: SystemType = SystemType.SIMPLE_BEAM,
            moment: MomentType = MomentType.MAX_POS_MOMENT,
            n: float = 0.0,
            debug_print: bool = False
    ) -> float:
        """
        Compute the ULS bending utilization ratio |M_Ed| / M_Rd.
        Adapted from Loutfi :cite:`loutfi_2023`

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.
        loads : Loads
            Applied loads object (uniformly distributed over all spans).
        system : SystemType, optional
            Structural system type. Default is
            :attr:`SystemType.SIMPLE_BEAM`.
        moment : MomentType, optional
            Governing moment type. Default is
            :attr:`MomentType.MAX_POS_MOMENT`.
        n : float, optional
            Applied normal force [N] (positive = tension). Default is
            ``0.0``.
        debug_print : bool, optional
            If ``True``, prints intermediate values (system, moment type,
            x-position, M_Rd, M_Ed, utilization) to console.
            Default is ``False``.

        Returns
        -------
        float
            Utilization ratio |M_Ed| / M_Rd [-]. Returns ``10.0`` for
            infeasible sections.
        """
        # Get moment data (coefficient and x-position) from lookup table
        moment_data = InternalForces.get_moment_data(system, moment)
        x_position = moment_data["x_position"]

        # Validate x-position is within bounds for this system
        InternalForces.validate_x_position(system, x_position)

        # Read resistance from the per-FE analysis cache.
        m_u_key = SectionResultKey(
            result_type="M_u",
            x=x_position,
            limit_state="ULS",
            n=n,
            flipped=moment != MomentType.MAX_POS_MOMENT,
        )
        res = slab_construction.analysis_cache.require_m_u(m_u_key)
        if not res.get("valid", True):
            return 10.

        if moment == MomentType.MAX_POS_MOMENT:
            MRd_kNm = -Nmm_to_kNm(res["m_u"])
        else:
            MRd_kNm = Nmm_to_kNm(res["m_u"])

        # Calculate design moment based on system and moment type
        MEd_kNm = InternalForces.calculate_moment_kNm(
            slab_construction,
            loads,
            system,
            combination="FUNDAMENTAL",
            moment=moment
        )

        # Calculate utilization
        utilization = abs(MEd_kNm / MRd_kNm)

        if debug_print:
            print(f"System: {system}, Moment Type: {moment}")
            print(f"x-position: {x_position:.3f}")
            print(f"M_Rd = {MRd_kNm:.3f} kNm")
            print(f"M_Ed = {MEd_kNm:.3f} kNm")
            print(f"Utilization = {utilization:.3f} ({utilization * 100:.1f}%)\n")

        return utilization


"""SERVICEABILITY LIMIT STATE"""


"""B.1a Deflection Limit Check"""


class DeflectionLimitByDeflectionCheckEC2004DE(StructuralCheck):
    """
    SLS deflection limit check by computed deflection (B.1a).

    Verifies that the maximum quasi-permanent deflection w does not
    exceed the span-based limit L / limit_factor. Negative deflections
    (upward camber) are treated as undesirable and penalized by
    returning ``1 + |utilization|``.

    Infeasible sections that raise :exc:`InvalidSectionForMKError` are
    penalized with a fixed utilization of ``10.0``.
    """

    @staticmethod
    def calculate_utilization(
            slab_construction: SlabConstruction,
            loads: Loads,
            system: SystemType = SystemType.SIMPLE_BEAM,
            limit_factor: float = 250.0,
            debug: bool = False,
    ) -> float:
        """
        Compute the SLS deflection utilization ratio w / (L / limit_factor).
        Adapted from Loutfi :cite:`loutfi_2023`

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.
        loads : Loads
            Applied loads object.
        system : SystemType, optional
            Structural system type. Default is
            :attr:`SystemType.SIMPLE_BEAM`.
        limit_factor : float, optional
            Span fraction used to derive the deflection limit
            w_limit = L / limit_factor [-]. Default is ``250.0``.
        debug : bool, optional
            If ``True``, passes debug flag to the deflection calculator
            and prints raw utilization, w_max, and L to console.
            Default is ``False``.

        Returns
        -------
        float
            Utilization ratio w_max / w_limit [-]. Returns ``10.0`` for
            infeasible sections. Negative deflections are returned as
            ``1 + |utilization|``.
        """
        try:
            w_max_sls = DeflectionCalculator.calculate_deflection_mm_EC(
                slab_construction,
                loads,
                system,
                load_history_method="NONE",
                m_k_simplification=DEFLECTION_MK_SIMPLIFICATION,
                m_k_simplification_softening=DEFLECTION_MK_SIMPLIFICATION_SOFTENING,
                combination="QUASI_PERMANENT",
                debug=debug,
            )
        except (InvalidSectionForMKError, RuntimeError) as e:
            if debug:
                print(f"[B1a] section infeasible for deflection calc: {e}")
            return 10.

        L = slab_construction.slab.L

        w_limit = L / limit_factor

        utilization = w_max_sls / w_limit

        if utilization < 0:
            # Negative deformation is undesirable
            screened_utilization = 1 + abs(utilization)
        else:
            screened_utilization = utilization

        if debug:
            print("raw util = ", utilization)
            print("w_max = ", w_max_sls)
            print("L = ", L)

        return screened_utilization


"""B.1b Deflection Limit Check"""


class DeflectionLimitByMcrCheckEC2004DE(StructuralCheck):
    """
    SLS deflection limit check by cracking moment comparison (B.1b).

    Verifies that the quasi-permanent design moment M_qp does not exceed
    the cracking moment M_cr. A utilization < 1.0 means the section
    remains uncracked; a utilization > 1.0 means the section will crack
    under quasi-permanent loads.

    Sections that crush before cracking (over-prestressed) or produce an
    invalid cracking moment result are penalized with ``10.0``.
    """

    @staticmethod
    def calculate_utilization(
            slab_construction: SlabConstruction,
            loads: Loads,
            system: SystemType = SystemType.SIMPLE_BEAM,
            moment: MomentType = MomentType.MAX_POS_MOMENT,
            n: float = 0.0,
            debug: bool = False
    ) -> float:
        """
        Compute the SLS cracking utilization ratio |M_qp| / M_cr.
        Adapted from Loutfi :cite:`loutfi_2023`

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.
        loads : Loads
            Applied loads object.
        system : SystemType, optional
            Structural system type. Default is
            :attr:`SystemType.SIMPLE_BEAM`.
        moment : MomentType, optional
            Governing moment type. Default is
            :attr:`MomentType.MAX_POS_MOMENT`.
        n : float, optional
            Applied normal force [N] (positive = tension). Default is
            ``0.0``.
        debug : bool, optional
            If ``True``, prints M_qp, M_cr validity, M_cr, and
            utilization to console. Default is ``False``.

        Returns
        -------
        float
            Utilization ratio |M_qp| / M_cr [-].

            - < 1.0: section remains uncracked under quasi-permanent loads.
            - > 1.0: section will crack.
            - ``10.0``: section crushes before cracking (invalid result).
        """
        # Calculate quasi-permanent moment
        m_qp_kNm = InternalForces.calculate_moment_kNm(
            slab_construction,
            loads,
            system,
            combination = "QUASI_PERMANENT",
            moment = moment,
        )

        m_cr_key = SectionResultKey(
            result_type="M_cr",
            x=0.5,
            limit_state="SLS",
            n=n,
        )
        m_cr_result = slab_construction.analysis_cache.require_m_cr(m_cr_key)

        # Handle invalid cases (section crushes before cracking)
        if not m_cr_result['valid']:
            return 10.

        # Get cracking moment magnitude
        m_cr = abs(Nmm_to_kNm(m_cr_result["m_cr"]))

        # Avoid division by zero (shouldn't happen with valid result, but safety check)
        if m_cr < 1e-6:
            return 10.

        # Calculate utilization (compare magnitudes)
        utilization = abs(m_qp_kNm) / m_cr

        if debug:
            print(f"m_qp = {m_qp_kNm:.3f} kNm")

            print(f"m_cr valid: {m_cr_result['valid']}")
            if not m_cr_result['valid']:
                print(f"  Reason: {m_cr_result['reason']}")

            print(f"m_cr = {m_cr:.3f} kNm")

            print(f"utilization = |{m_qp_kNm:.3f}| / {m_cr:.3f} = {utilization:.3f}")

        return utilization


"""B.2a Failure Announcement"""


class FailureAnnouncementByDeflectionCheckEC2004DE(StructuralCheck):
    """
    Failure announcement check by deflection under fundamental loads (B.2a).

    Verifies that the deflection under the fundamental load combination
    w_uls exceeds the minimum ductility threshold w_min = L / min_factor,
    so that a sufficient warning is ensured.
    A utilization ≤ 1.0 means the deflection at failure is large enough.

    Negative deflections (upward camber under ULS loads) are treated as
    undesirable and penalized by returning ``1 + |utilization|``.
    Infeasible sections are penalized with ``10.0``.
    """

    @staticmethod
    def calculate_utilization(
            slab_construction: SlabConstruction,
            loads: Loads,
            system: SystemType = SystemType.SIMPLE_BEAM,
            min_factor: float = 250.0,
            debug: bool = False,
    ) -> float:
        """
        Compute the failure announcement utilization ratio w_min / w_uls.
        Adapted from Loutfi :cite:`loutfi_2023`

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.
        loads : Loads
            Applied loads object.
        system : SystemType, optional
            Structural system type. Default is
            :attr:`SystemType.SIMPLE_BEAM`.
        min_factor : float, optional
            Span fraction used to derive the minimum required deflection
            w_min = L / min_factor [-]. Default is ``250.0``.
        debug : bool, optional
            If ``True``, passes debug flag to the deflection calculator
            and prints w_max, w_min, and utilization to console.
            Default is ``False``.

        Returns
        -------
        float
            Utilization ratio w_min / w_uls [-]. Returns ``10.0`` for
            infeasible sections. Negative deflections are returned as
            ``1 + |utilization|``.
        """
        try:
            w_max_uls = DeflectionCalculator.calculate_deflection_mm_EC(
                slab_construction,
                loads,
                system,
                load_history_method="NONE",
                m_k_simplification=DEFLECTION_MK_SIMPLIFICATION,
                m_k_simplification_softening=DEFLECTION_MK_SIMPLIFICATION_SOFTENING,
                combination="FUNDAMENTAL",
                debug=debug,
            )
        except (InvalidSectionForMKError, RuntimeError) as e:
            if debug:
                print(f"[B2a] section infeasible for deflection calc: {e}")
            return 10.

        L = slab_construction.slab.L

        w_min = L / min_factor


        utilization = w_min / w_max_uls

        if utilization < 0:
            # Negative deformation is undesirable
            screened_utilization = 1 + abs(utilization)
        else:
            screened_utilization = utilization

        if debug:
            print(f"w_max = {w_max_uls:.2f}")
            print(f"w_min = {w_min:.2f}")
            print(f"util raw = {w_min:.2f} / {w_max_uls:.2f} = {utilization:.2f}")
            print(f"util = {screened_utilization:.2f}")

        return screened_utilization


"""B.2b Failure Announcement"""


class FailureAnnouncementByMcrCheckEC2004DE(StructuralCheck):
    """
    Failure announcement check by cracking moment under fundamental loads (B.2b).

    Verifies that the cracking moment M_cr exceeds the fundamental design
    moment M_fund, ensuring that the section cracks before reaching ULS
    (brittle failure without warning is avoided). A utilization ≤ 1.0
    means M_cr < M_fund, i.e. the section cracks first.

    Sections that crush before cracking or produce an invalid cracking
    moment result are penalized with ``10.0``.
    """

    @staticmethod
    def calculate_utilization(
            slab_construction: SlabConstruction,
            loads: Loads,
            system: SystemType = SystemType.SIMPLE_BEAM,
            moment: MomentType = MomentType.MAX_POS_MOMENT,
            n: float = 0.0,
            debug: bool = False
    ) -> float:
        """
        Compute the failure announcement utilization ratio M_cr / M_fund.
        Adapted from Loutfi :cite:`loutfi_2023`

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.
        loads : Loads
            Applied loads object.
        system : SystemType, optional
            Structural system type. Default is
            :attr:`SystemType.SIMPLE_BEAM`.
        moment : MomentType, optional
            Governing moment type. Default is
            :attr:`MomentType.MAX_POS_MOMENT`.
        n : float, optional
            Applied normal force [N] (positive = tension). Default is
            ``0.0``.
        debug : bool, optional
            If ``True``, prints M_fund, M_cr validity, M_cr, and
            utilization to console. Default is ``False``.

        Returns
        -------
        float
            Utilization ratio M_cr / M_fund [-].

            - < 1.0: section cracks before reaching ULS
            - > 1.0: section reaches ULS without cracking
            - ``10.0``: section crushes before cracking
        """
        # Calculate fundamental combination moment
        m_fund_kNm = InternalForces.calculate_moment_kNm(
            slab_construction,
            loads,
            system,
            combination = "FUNDAMENTAL",
            moment = moment,
        )

        m_cr_key = SectionResultKey(
            result_type="M_cr",
            x=0.5,
            limit_state="SLS",
            n=n,
        )
        m_cr_result = slab_construction.analysis_cache.require_m_cr(m_cr_key)

        # Handle invalid cases (section crushes before cracking)
        if not m_cr_result['valid']:
            return 10.

        # Get cracking moment magnitude
        m_cr = abs(Nmm_to_kNm(m_cr_result["m_cr"]))

        # Avoid division by zero (shouldn't happen with valid result, but safety check)
        if m_cr < 1e-6:
            return 10.

        # Calculate utilization (compare magnitudes)
        utilization = m_cr / m_fund_kNm

        if debug:
            print(f"m_fund = {m_fund_kNm:.3f} kNm")

            print(f"m_cr valid: {m_cr_result['valid']}")
            if not m_cr_result['valid']:
                print(f"  Reason: {m_cr_result['reason']}")

            print(f"m_cr = {m_cr:.3f} kNm")

            print(f"utilization = {m_cr:.3f}/ {m_fund_kNm:.3f} = {utilization:.3f}")

        return utilization
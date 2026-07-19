"""
Construction feasibility checks for HP-shell slab constructions
Numbering according to Loutfi :cite:`loutfi_2023`

Verifies that the chosen geometry and reinforcement layout are
constructable: sufficient concrete cover, adequate bar spacing, and
minimum shell thickness.

Adapted from: Jamila Loutfi :cite:`loutfi_2023`
"""
from abc import ABC, abstractmethod

import numpy as np

from slab_construction.slab_construction import SlabConstruction


class ConstructionCheck(ABC):
    """
    Abstract base class for construction feasibility checks.
    Author: Elliot Melcer

    All ConstructionCheck subclasses must implement :meth:`calculate_utilization`,
    which returns a dimensionless utilization ratio where values ≤ 1.0
    indicate a constructable design.
    """

    @staticmethod
    @abstractmethod
    def calculate_utilization(
            slab_construction: SlabConstruction) -> float:
        """
        Compute the construction utilization ratio for a slab construction.

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.

        Returns
        -------
        float
            Utilization ratio [-]. Values ≤ 1.0 indicate a passing design.
        """
        raise NotImplementedError


"""C.1. Check for Sufficient Concrete Cover from the outermost Reinforcement to the Edge along the HP-Shell Midline """


class MidlineConcreteCoverCheck(ConstructionCheck):
    """
    Concrete cover check along the HP-shell midline (C.1).

    Verifies that the available clear concrete cover c_1 satisfies the
    minimum requirement c_nom,req = 3 · d_p, where d_p is the equivalent
    bar diameter of the outermost reinforcement layer.

    A utilization ≤ 1.0 means the concrete cover is sufficient. Infeasible
    designs (c_1 = 0) are penalized with a fixed utilization of 10.0.
    """

    @staticmethod
    def calculate_utilization(slab_construction: SlabConstruction) -> float:
        """
        Compute the concrete cover utilization ratio c_nom,req / c_1.

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.

        Returns
        -------
        float
            Utilization ratio c_nom,req / c_1 [-]. Returns ``10.0`` if the
            available cover is zero (infeasible design).
        """
        # get geometry
        hp_shell = slab_construction.slab.hp_shell

        # required clear concrete cover
        d_p_mm = hp_shell.d_p()
        c_nom_c1_req = 3 * d_p_mm

        # available clear concrete cover
        c_nom_c1 = hp_shell.c_1_clear_concrete_cover()

        # infeasible design
        if c_nom_c1 == 0:
            return 10.

        utilization = c_nom_c1_req / c_nom_c1

        return utilization


"""C.2. Check for Sufficient Clear Spacing between Reinforcement along the HP-Shell Midline """


class ReinforcementSpacingCheck(ConstructionCheck):
    """
    Clear reinforcement spacing check along the HP-shell midline (C.2).

    Verifies that the minimum available spacing s_min between
    reinforcement bars satisfies s_req = 5.75 · d_p.

    A utilization ≤ 1.0 means the spacing is sufficient. Infeasible
    designs (s_min = 0) are penalized with a fixed utilization of 10.0.
    """

    @staticmethod
    def calculate_utilization(slab_construction: SlabConstruction, debug_print: bool = False) -> float:
        """
        Compute the reinforcement spacing utilization ratio s_req / s_min.

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.
        debug_print : bool, optional
            If ``True``, prints the minimum available clear spacing to
            console. Default is ``False``.

        Returns
        -------
        float
            Utilization ratio s_req / s_min [-]. Returns ``10.0`` if the
            minimum spacing is zero (infeasible design).
        """
        # get geometry
        hp_shell = slab_construction.slab.hp_shell

        # required reinforcement spacing
        d_p_mm = hp_shell.d_p()
        s_req = 5.75 * d_p_mm

        # minimum available clear spacing
        s_min = hp_shell.s_min_clear_reinf_spacing()

        if debug_print:
            print(f"s_min = {s_min}")

        if s_min == 0:
            return 10.
        else:
            utilization = s_req / s_min

        return utilization


"""C.3. Check for Minimum Shell Thickness """


class MinimumHPShellThicknessCheck(ConstructionCheck):
    """
    Minimum HP-shell thickness check (C.3).

    Derives the required shell thickness from the combined C.1 and C.2
    requirements:

    A utilization ≤ 1.0 means the shell is thick enough to accommodate
    the reinforcement with the required cover and spacing.
    """

    @staticmethod
    def calculate_utilization(slab_construction: SlabConstruction) -> float:
        """
        Compute the shell thickness utilization ratio t_req / t.

        Parameters
        ----------
        slab_construction : SlabConstruction
            Full slab construction object.

        Returns
        -------
        float
            Utilization ratio t_req / t [-].
        """
        # get geometry
        hp_shell = slab_construction.slab.hp_shell

        # required clear concrete cover
        d_p_mm = hp_shell.d_p()

        # C.1 an C.2 requirements
        c_nom_c1_req = 3 * d_p_mm
        s_c2_req = 5.75 * d_p_mm

        # shell thickness
        t_req = 2 * d_p_mm + 2 * c_nom_c1_req + s_c2_req

        # available clear concrete cover
        t = hp_shell.hp_geometry.t

        utilization = t_req / t

        return utilization
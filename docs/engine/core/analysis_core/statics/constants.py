"""
Enumerations and lookup tables for structural system types, moment types,
and moment coefficients used in the internal forces module.
"""
from typing import Dict
from enum import Enum


class SystemType(str, Enum):
    """Enumeration of supported structural system types."""

    CANTILEVER = "CANTILEVER"
    SIMPLE_BEAM = "SIMPLE_BEAM"
    TWO_SPAN = "TWO_SPAN"
    THREE_SPAN = "THREE_SPAN"
    FOUR_SPAN = "FOUR_SPAN"
    FIVE_SPAN = "FIVE_SPAN"


class MomentType(str, Enum):
    """Enumeration of governing moment types."""

    MAX_POS_MOMENT = "MAX_POS_MOMENT"
    MAX_NEG_MOMENT = "MAX_NEG_MOMENT"


"""
Maximum valid x-position for each system type.
x = 0 at first support, x = 1 at second support, etc.

  |-> x
  0      0.5      1      1.5      2

  ====================================|...
  ^               ^               ^
"""

MAX_X_POSITIONS: Dict[str, float] = {
    "CANTILEVER": 1.0,    # From support (0) to free end (1)
    "SIMPLE_BEAM": 1.0,   # From support 0 to support 1
    "TWO_SPAN": 2.0,      # Supports at 0, 1, 2
    "THREE_SPAN": 3.0,    # Supports at 0, 1, 2, 3
    "FOUR_SPAN": 4.0,     # Supports at 0, 1, 2, 3, 4
    "FIVE_SPAN": 5.0,     # Supports at 0, 1, 2, 3, 4, 5
}


"""
Lookup table for moment coefficients and governing x-positions 
according to :cite:`schneider_2016` and/or Stab2D-calculations

M = coefficient · w · L²

Keys: system name → moment type → {coefficient, x_position}.
x_position-values for multi-span systems are derived from Stab2D-NL analyses.
"""

MOMENT_DATA: Dict[str, Dict[str, Dict[str, float]]] = {
    "CANTILEVER": {
        "MAX_POS_MOMENT": {
            "coefficient": 0.000,
            "x_position": 0.0,       # N/A, MAX_POS_MOMENT caught as error
        },
        "MAX_NEG_MOMENT": {
            "coefficient": -0.500,
            "x_position": 0.0,
        },
    },
    "SIMPLE_BEAM": {
        "MAX_POS_MOMENT": {
            "coefficient": 0.125,
            "x_position": 0.5,
        },
        "MAX_NEG_MOMENT": {
            "coefficient": 0.000,
            "x_position": 0.0,       # N/A MAX_NEG_MOMENT caught as error
        },
    },
    "TWO_SPAN": {
        "MAX_POS_MOMENT": {
            "coefficient": 0.070,
            "x_position": 0.390,       # from Stab2D-NL Analysis
        },
        "MAX_NEG_MOMENT": {
            "coefficient": -0.125,
            "x_position": 1.0,
        },
    },
    "THREE_SPAN": {
        "MAX_POS_MOMENT": {
            "coefficient": 0.080,
            "x_position": 0.404,       # from Stab2D-NL Analysis
        },
        "MAX_NEG_MOMENT": {
            "coefficient": -0.100,
            "x_position": 1.0,
        },
    },
    "FOUR_SPAN": {
        "MAX_POS_MOMENT": {
            "coefficient": 0.077,
            "x_position": 0.404,       # from Stab2D-NL Analysis
        },
        "MAX_NEG_MOMENT": {
            "coefficient": -0.107,
            "x_position": 1.0,
        },
    },
    "FIVE_SPAN": {
        "MAX_POS_MOMENT": {
            "coefficient": 0.078,
            "x_position": 0.404,       # from Stab2D-NL Analysis
        },
        "MAX_NEG_MOMENT": {
            "coefficient": -0.105,
            "x_position": 1.0,
        },
    },
}
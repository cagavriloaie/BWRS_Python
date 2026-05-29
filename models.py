from dataclasses import dataclass, field
from enum import IntEnum
from constants import KAPPA_DEFAULT


class DeviceType(IntEnum):
    ORIFICE_CORNER      = 1
    ORIFICE_FLANGE      = 2
    ORIFICE_DD2         = 3
    NOZZLE_ISA          = 4
    NOZZLE_LONG_RADIUS  = 5
    VENTURI_ROUGH_CAST  = 6
    VENTURI_MACHINED    = 7
    VENTURI_WELDED_SHEET = 8
    VENTURI_NOZZLE      = 9


class ErrorCode(IntEnum):
    PIPE_DIAMETER    = 1
    ORIFICE_DIAMETER = 2
    THROTTLE_RATIO   = 3
    REYNOLDS         = 4
    NUMERIC          = 5


@dataclass
class BwrConst:
    m_a0:        float = 0.0
    m_b0:        float = 0.0
    m_c0:        float = 0.0
    m_d0:        float = 0.0
    m_e0:        float = 0.0
    m_a:         float = 0.0
    m_b:         float = 0.0
    m_c:         float = 0.0
    m_dv:        float = 0.0
    m_alpha:     float = 0.0
    m_gamma:     float = 0.0
    m_molarMass: float = 0.0


@dataclass
class MixtureThermo:
    m_rocCrit: float = 0.0
    m_csi:     float = 0.0


@dataclass
class FlowResult:
    m_velocity:     float = 0.0
    m_pressureLoss: float = 0.0
    m_beta:         float = 0.0
    m_reynolds:     float = 0.0
    m_coefC:        float = 0.0
    m_epsilon:      float = 0.0
    m_dWorkingMm:   float = 0.0
    m_DWorkingMm:   float = 0.0
    m_kappa:        float = KAPPA_DEFAULT


@dataclass
class CountryRef:
    m_name:  str
    m_n:     int
    m_t:     list   # up to 2 reference temperatures [°C]
    m_label: list   # up to 2 unit labels


TIP_MIN = int(DeviceType.ORIFICE_CORNER)
TIP_MAX = int(DeviceType.VENTURI_NOZZLE)


def is_diaphragm(tip: DeviceType) -> bool:
    return int(tip) <= int(DeviceType.ORIFICE_DD2)


def tip_name(tip: DeviceType) -> str:
    names = {
        DeviceType.ORIFICE_CORNER:       "Orifice plate — corner taps",
        DeviceType.ORIFICE_FLANGE:       "Orifice plate — flange taps",
        DeviceType.ORIFICE_DD2:          "Orifice plate — D and D/2 taps",
        DeviceType.NOZZLE_ISA:           "ISA 1932 nozzle",
        DeviceType.NOZZLE_LONG_RADIUS:   "Long-radius nozzle",
        DeviceType.VENTURI_ROUGH_CAST:   "Classical Venturi tube — rough-cast convergent",
        DeviceType.VENTURI_MACHINED:     "Classical Venturi tube — machined convergent",
        DeviceType.VENTURI_WELDED_SHEET: "Classical Venturi tube — rough-welded sheet-metal convergent",
        DeviceType.VENTURI_NOZZLE:       "Venturi nozzle",
    }
    return names.get(tip, "")


TIP_DISPLAY = (
    "\n  Throttling device:\n\n"
    "  1.  Orifice plate — corner taps\n"
    "  2.  Orifice plate — flange taps\n"
    "  3.  Orifice plate — D and D/2 taps\n"
    "  4.  ISA 1932 nozzle\n"
    "  5.  Long-radius nozzle\n"
    "  6.  Classical Venturi tube — rough-cast convergent\n"
    "  7.  Classical Venturi tube — machined convergent\n"
    "  8.  Classical Venturi tube — rough-welded sheet-metal convergent\n"
    "  9.  Venturi nozzle\n\n"
    "  Select (1–9) >"
)

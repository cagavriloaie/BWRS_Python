import math

from constants import (
    NUM_COMPONENTS, KELVIN_OFFSET, CHAP_ENSKOG,
    VISC_HIGH_A, VISC_HIGH_EXP1, VISC_HIGH_EXP2, VISC_HIGH_POW,
)
from data.components import MOLAR_MASS_TABLE, VISC_CS_PARAM, VISC_ET_PARAM


def calc_viscosity(t_celsius: float, ro: float, x: list,
                   roc_crit: float, csi: float) -> float:
    """Compute dynamic viscosity η [Pa·s] using Chapman-Enskog dilute-gas model
    with Chung-Lee-Starling high-density correction.
    t_celsius [°C], ro [kg/m³], roc_crit [kg/m³], csi — viscosity parameter."""
    t_k    = t_celsius + KELVIN_OFFSET
    roc_red = ro / roc_crit

    # Σ xᵢ √Mᵢ — denominator of Chapman-Enskog mixing rule
    mx_sum = sum(x[i] * math.sqrt(MOLAR_MASS_TABLE[i]) for i in range(1, NUM_COMPONENTS + 1))

    # Dilute-gas mixture viscosity
    viscosity = 0.0
    for i in range(1, NUM_COMPONENTS + 1):
        viscosity += (
            (1.0 + CHAP_ENSKOG * math.log(t_k / VISC_CS_PARAM[i]))
            / (1.0 + CHAP_ENSKOG * math.log(KELVIN_OFFSET / VISC_CS_PARAM[i]))
            * math.sqrt(t_k / KELVIN_OFFSET)
            * VISC_ET_PARAM[i] * x[i] * math.sqrt(MOLAR_MASS_TABLE[i])
        )
    viscosity /= mx_sum

    # High-density correction
    viscosity += (VISC_HIGH_A / csi) * (
        math.exp(VISC_HIGH_EXP1 * roc_red) - math.exp(-VISC_HIGH_EXP2 * roc_red)
    ) ** VISC_HIGH_POW

    return viscosity

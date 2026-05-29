import math

from constants import (
    NUM_COMPONENTS, GAS_CONSTANT_R, KELVIN_OFFSET, BWRS_MIX_COEF,
    RO_MIN, RO_MAX, MAX_DENSITY_ITER, DENSITY_TOLERANCE,
    GAS_CONSTANT_RSI,
)
from data.components import (
    BWRS_A0, BWRS_B0, BWRS_C0, BWRS_A, BWRS_B, BWRS_C,
    BWRS_ALFA, BWRS_GAMA, BWRS_V, BWRS_D0, BWRS_E0, BWRS_DV,
    MOLAR_MASS_TABLE, TEMP_CRITICAL_TABLE, PRESS_CRITICAL_TABLE,
    Z_CRITICAL_TABLE, CP0_IDEAL,
)
from models import BwrConst, MixtureThermo


_TRIPLE_THRESH = 1e-9    # skip i-j pairs whose product is negligible; since x[l]≤1, xi*xj*xl≤xi*xj, so the whole l-loop contributes nothing above this threshold


def calc_bwr_mixture(x: list) -> BwrConst:
    """Compute BWRS mixture constants from molar fractions x[1..NUM_COMPONENTS].
    Starling (1973) quadratic and cubic mixing rules."""
    bt = BwrConst()

    # Iterate only over components with non-zero mole fraction.
    active = [i for i in range(1, NUM_COMPONENTS + 1) if x[i] > 0.0]

    # Pairwise binary interaction coefficients; each involves sqrt+cbrt so precompute
    # once and share between the quadratic and cubic loops.
    v_sq = {i: math.sqrt(BWRS_V[i]) for i in active}
    v_cb = {i: BWRS_V[i] ** (1/3)   for i in active}
    k_pair = {
        (i, j): 1.0 - BWRS_MIX_COEF * v_sq[i] * v_sq[j] / (v_cb[i] + v_cb[j]) ** 3
        for i in active for j in active
    }

    # Quadratic (2nd-order) mixing rules: A0, B0, C0, D0, E0, gamma
    for i in active:
        for j in active:
            kk    = k_pair[i, j]
            xi_xj = x[i] * x[j]
            bt.m_a0    += xi_xj * math.sqrt(BWRS_A0[i] * BWRS_A0[j]) * (1 - kk)
            bt.m_b0    += xi_xj * math.sqrt(BWRS_B0[i] * BWRS_B0[j])
            bt.m_c0    += xi_xj * math.sqrt(BWRS_C0[i] * BWRS_C0[j]) * (1 - kk) ** 3
            bt.m_d0    += xi_xj * math.sqrt(BWRS_D0[i] * BWRS_D0[j]) * (1 - kk) ** 4
            bt.m_e0    += xi_xj * math.sqrt(BWRS_E0[i] * BWRS_E0[j]) * (1 - kk) ** 5
            bt.m_gamma += xi_xj * math.sqrt(BWRS_GAMA[i] * BWRS_GAMA[j])

    # Cube roots factored out: (a_i*a_j*a_l)^(1/3) = ca_i * ca_j * ca_l
    cbrt_a  = {i: BWRS_A[i]     ** (1/3) for i in active}
    cbrt_b  = {i: BWRS_B[i]     ** (1/3) for i in active}
    cbrt_c  = {i: BWRS_C[i]     ** (1/3) for i in active}
    cbrt_dv = {i: BWRS_DV[i]    ** (1/3) for i in active}
    cbrt_al = {i: BWRS_ALFA[i]  ** (1/3) for i in active}

    # Cubic (3rd-order) mixing rules: a, b, c, d, alpha
    for i in active:
        xi    = x[i]
        ca_i  = cbrt_a[i];  cb_i  = cbrt_b[i];  cc_i   = cbrt_c[i]
        cdv_i = cbrt_dv[i]; cal_i = cbrt_al[i]
        for j in active:
            xij = xi * x[j]
            if xij < _TRIPLE_THRESH:    # entire l-loop contributes < threshold; skip
                continue
            m1      = 1.0 - k_pair[i, j]
            cab_ij  = ca_i  * cbrt_a[j]
            cbb_ij  = cb_i  * cbrt_b[j]
            ccb_ij  = cc_i  * cbrt_c[j]
            cdvb_ij = cdv_i * cbrt_dv[j]
            calb_ij = cal_i * cbrt_al[j]
            for l in active:
                xijl  = xij * x[l]
                kprod = m1 * (1.0 - k_pair[i, l]) * (1.0 - k_pair[j, l])
                bt.m_a     += xijl * cab_ij  * cbrt_a[l]  * kprod
                bt.m_b     += xijl * cbb_ij  * cbrt_b[l]
                bt.m_c     += xijl * ccb_ij  * cbrt_c[l]  * kprod
                bt.m_dv    += xijl * cdvb_ij * cbrt_dv[l] * kprod
                bt.m_alpha += xijl * calb_ij * cbrt_al[l]

    for i in range(1, NUM_COMPONENTS + 1):
        bt.m_molarMass += x[i] * MOLAR_MASS_TABLE[i]

    return bt


def _pressure_at(ro: float, t_k: float, bwr: BwrConst) -> float:
    """BWRS equation: pressure [atm] at molar density ro [mol/L] and T [K]."""
    t2 = t_k * t_k
    t3 = t2 * t_k
    t4 = t3 * t_k
    exp_gr2 = math.exp(-bwr.m_gamma * ro * ro)
    return (
        GAS_CONSTANT_R * t_k * ro
        + (bwr.m_b0 * GAS_CONSTANT_R * t_k - bwr.m_a0 - bwr.m_c0 / t2
           + bwr.m_d0 / t3 - bwr.m_e0 / t4) * ro * ro
        + (bwr.m_b * GAS_CONSTANT_R * t_k - bwr.m_a - bwr.m_dv / t_k) * ro ** 3
        + bwr.m_alpha * (bwr.m_a + bwr.m_dv / t_k) * ro ** 6
        + (bwr.m_c / t2) * ro ** 3 * (1.0 + bwr.m_gamma * ro * ro) * exp_gr2
    )


def _dpressure_dro(ro: float, t_k: float, bwr: BwrConst) -> float:
    """Analytical dP/dρ of BWRS EOS [atm·L/mol]; used for Newton-Raphson steps."""
    t2  = t_k * t_k
    t3  = t2  * t_k
    t4  = t3  * t_k
    g   = bwr.m_gamma
    ro2 = ro * ro
    return (
        GAS_CONSTANT_R * t_k
        + 2.0 * (bwr.m_b0 * GAS_CONSTANT_R * t_k - bwr.m_a0 - bwr.m_c0 / t2
                 + bwr.m_d0 / t3 - bwr.m_e0 / t4) * ro
        + 3.0 * (bwr.m_b * GAS_CONSTANT_R * t_k - bwr.m_a - bwr.m_dv / t_k) * ro2
        + 6.0 * bwr.m_alpha * (bwr.m_a + bwr.m_dv / t_k) * ro2 * ro2 * ro
        + (bwr.m_c / t2) * math.exp(-g * ro2) * ro2 * (3.0 + 3.0 * g * ro2 - 2.0 * g * g * ro2 * ro2)
    )


def calc_density(t: float, p: float, bwr: BwrConst):
    """Solve BWRS for gas-phase density [kg/m³] via bisection + Newton-Raphson.
    t [°C], p [atm]. Returns (density, iters); density=0 on failure."""
    t_k = t + KELVIN_OFFSET
    if not (math.isfinite(t_k) and math.isfinite(p) and math.isfinite(bwr.m_molarMass)
            and t_k > 0.0 and p > 0.0 and bwr.m_molarMass > 0.0):
        return 0.0, 0

    # Adaptive bracket
    ro1  = RO_MIN
    p_lo = _pressure_at(ro1, t_k, bwr)
    ro2  = max(p / (GAS_CONSTANT_R * t_k), ro1 * 2.0)
    p_hi = _pressure_at(ro2, t_k, bwr)
    p_prev = p_lo
    for _ in range(60):
        if not math.isfinite(p_hi) or p_hi < p_prev:
            break
        if p_hi >= p:
            break
        p_prev = p_hi
        ro1 = ro2;  p_lo = p_hi
        ro2 = min(ro2 * 2.0, RO_MAX)
        p_hi = _pressure_at(ro2, t_k, bwr)

    if not (math.isfinite(p_lo) and math.isfinite(p_hi) and p_lo <= p <= p_hi):
        return 0.0, 0

    for n_iter in range(1, MAX_DENSITY_ITER + 1):
        mid   = (ro1 + ro2) * 0.5
        p_mid = _pressure_at(mid, t_k, bwr)
        if not math.isfinite(p_mid):
            return 0.0, n_iter

        # Try NR from midpoint; keep bisection result if step escapes bracket.
        ro, p_cal = mid, p_mid
        dp = _dpressure_dro(mid, t_k, bwr)
        if dp > 0.0:
            ro_nr = mid - (p_mid - p) / dp
            if ro1 < ro_nr < ro2:
                p_nr = _pressure_at(ro_nr, t_k, bwr)
                if math.isfinite(p_nr):
                    ro, p_cal = ro_nr, p_nr

        if abs(p - p_cal) < max(DENSITY_TOLERANCE, abs(p) * 1e-6):
            return bwr.m_molarMass * ro, n_iter
        if p_cal > p:
            ro2 = ro
        else:
            ro1 = ro
    return 0.0, MAX_DENSITY_ITER


def calc_mixture_thermo(x: list, bwr: BwrConst) -> MixtureThermo:
    """Compute pseudo-critical properties (Kay's rule) for viscosity model."""
    tc_mix = pc_mix = zc_mix = 0.0
    for i in range(1, NUM_COMPONENTS + 1):
        tc_mix += x[i] * TEMP_CRITICAL_TABLE[i]
        pc_mix += x[i] * PRESS_CRITICAL_TABLE[i]
        zc_mix += x[i] * Z_CRITICAL_TABLE[i]
    thermo = MixtureThermo()
    # mol/L × g/mol = g/L = kg/m³  (since 1 g/L = 1 kg/m³), so roc_red = ro/roc_crit is dimensionless
    thermo.m_rocCrit = pc_mix / (GAS_CONSTANT_R * zc_mix * tc_mix) * bwr.m_molarMass
    thermo.m_csi     = (tc_mix ** (1/6)) / math.sqrt(bwr.m_molarMass) / (pc_mix * pc_mix) ** (1/3)
    return thermo


def calc_kappa(x: list) -> float:
    """Isentropic exponent κ = Cp° / (Cp° − R) at 20 °C."""
    cp_mix = sum(x[i] * CP0_IDEAL[i] for i in range(1, NUM_COMPONENTS + 1))
    return cp_mix / (cp_mix - GAS_CONSTANT_RSI)

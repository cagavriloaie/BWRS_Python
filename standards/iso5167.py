import math

from constants import (
    PI, FLANGE_TAP_M, REYNOLDS_ISO_REF, INITIAL_REYNOLDS, REYNOLDS_TOLERANCE,
    MAX_REYNOLDS_ITER, THERMAL_EXP_PIPE, THERMAL_EXP_ORIFICE, REF_TEMP_CELSIUS,
    FACTOR_2KPA, KAPPA_DEFAULT,
)
from models import DeviceType, ErrorCode, FlowResult, is_diaphragm


def print_error(code: ErrorCode, reynolds_num: float = 0.0) -> str:
    msgs = {
        ErrorCode.PIPE_DIAMETER:    "\n  Pipe inner diameter is out of range\n",
        ErrorCode.ORIFICE_DIAMETER: "\n  Throttling device orifice diameter is out of range\n",
        ErrorCode.THROTTLE_RATIO:   "\n  Throttling ratio β is out of range\n",
        ErrorCode.REYNOLDS:         f"\n  Reynolds number ({reynolds_num:g}) is out of range\n",
        ErrorCode.NUMERIC:          "\n  Numerical error — check that inputs are in a physically valid range\n",
    }
    return msgs.get(code, "").strip()


def discharge_coefficient(tip: DeviceType, pipe_diam_m: float,
                           beta: float, reynolds_num: float) -> float:
    """Discharge coefficient C per ISO 5167-2/3/4 (Reader-Harris/Gallagher)."""
    if tip in (DeviceType.ORIFICE_CORNER, DeviceType.ORIFICE_FLANGE, DeviceType.ORIFICE_DD2):
        if tip == DeviceType.ORIFICE_CORNER:
            tap_l1 = 0.0;  tap_l2p = 0.0
        elif tip == DeviceType.ORIFICE_FLANGE:
            tap_l1 = FLANGE_TAP_M / pipe_diam_m;  tap_l2p = tap_l1
        else:
            tap_l1 = 1.0;  tap_l2p = 0.50

        rhg_a  = (19000.0 * beta / reynolds_num) ** 0.8
        m2_tap = 2.0 * tap_l2p / (1.0 - beta)
        c = (0.5961
             + 0.0261 * beta ** 2
             - 0.216  * beta ** 8
             + 0.000521 * (1.0e6 * beta / reynolds_num) ** 0.7
             + (0.0188 + 0.0063 * rhg_a) * beta ** 3.5 * (1.0e6 / reynolds_num) ** 0.3
             + (0.043 + 0.080 * math.exp(-10.0 * tap_l1) - 0.123 * math.exp(-7.0 * tap_l1))
               * (1.0 - 0.11 * rhg_a) * beta ** 4 / (1.0 - beta ** 4)
             - 0.031 * (m2_tap - 0.8 * m2_tap ** 1.1) * beta ** 1.3)
        if pipe_diam_m < 0.07112:
            c += 0.011 * (0.75 - beta) * (2.8 - pipe_diam_m / FLANGE_TAP_M)
        return c

    if tip == DeviceType.NOZZLE_ISA:
        return (0.99 - 0.2262 * beta ** 4.1
                + (0.000215 - 0.001125 * beta + 0.00249 * beta ** 4.7)
                * (REYNOLDS_ISO_REF / reynolds_num) ** 1.15)

    if tip == DeviceType.NOZZLE_LONG_RADIUS:
        return 0.9965 - 0.00653 * math.sqrt(beta) * math.sqrt(REYNOLDS_ISO_REF / reynolds_num)

    if tip == DeviceType.VENTURI_ROUGH_CAST:   return 0.984
    if tip == DeviceType.VENTURI_MACHINED:     return 0.995
    if tip == DeviceType.VENTURI_WELDED_SHEET: return 0.985
    if tip == DeviceType.VENTURI_NOZZLE:       return 0.9858 - 0.196 * beta ** 4.5
    return 0.0


def velocity_coefficient(tip: DeviceType, pipe_diam_m: float,
                          beta: float, reynolds_num: float) -> float:
    """Velocity coefficient α = C / √(1 − β⁴)."""
    return discharge_coefficient(tip, pipe_diam_m, beta, reynolds_num) / math.sqrt(1.0 - beta ** 4)


def calc_mass_flow(dp: float, p: float, t: float,
                   tip: DeviceType, d_int: float, d_orif: float,
                   ro: float, eta: float,
                   kappa: float = KAPPA_DEFAULT):
    """Mass flow rate [kg/s] via ISO 5167 Reynolds iteration.
    dp, p [kPa]; t [°C]; d_int, d_orif [mm]; ro [kg/m³]; eta [Pa·s].
    Returns (qm, FlowResult, n_iters, error_msg); qm=0 and error_msg non-empty on failure."""
    out = FlowResult()

    if not (math.isfinite(dp) and math.isfinite(p) and math.isfinite(t)
            and math.isfinite(d_int) and math.isfinite(d_orif)
            and math.isfinite(ro) and math.isfinite(eta)
            and dp > 0.0 and p > 0.0 and dp < p and ro > 0.0 and eta > 0.0):
        return 0.0, out, 0, print_error(ErrorCode.NUMERIC)

    d_pipe_t  = d_int  * (1.0 + THERMAL_EXP_PIPE    * (t - REF_TEMP_CELSIUS))
    d_orif_t  = d_orif * (1.0 + THERMAL_EXP_ORIFICE * (t - REF_TEMP_CELSIUS))

    # Pipe diameter range checks
    if d_pipe_t < 50:
        return 0.0, out, 0, print_error(ErrorCode.PIPE_DIAMETER)
    pipe_too_big = (
        (d_pipe_t > 1000 and tip == DeviceType.ORIFICE_CORNER) or
        (d_pipe_t > 760  and tip in (DeviceType.ORIFICE_FLANGE, DeviceType.ORIFICE_DD2)) or
        (d_pipe_t > 500  and tip == DeviceType.NOZZLE_ISA) or
        (d_pipe_t > 630  and tip == DeviceType.NOZZLE_LONG_RADIUS) or
        (d_pipe_t > 800  and tip == DeviceType.VENTURI_ROUGH_CAST) or
        (d_pipe_t < 100  and tip == DeviceType.VENTURI_ROUGH_CAST) or
        (d_pipe_t > 250  and tip == DeviceType.VENTURI_MACHINED) or
        (d_pipe_t < 50   and tip == DeviceType.VENTURI_MACHINED) or
        (d_pipe_t > 1200 and tip == DeviceType.VENTURI_WELDED_SHEET) or
        (d_pipe_t < 200  and tip == DeviceType.VENTURI_WELDED_SHEET) or
        (d_pipe_t > 500  and tip == DeviceType.VENTURI_NOZZLE) or
        (d_pipe_t < 65   and tip == DeviceType.VENTURI_NOZZLE)
    )
    if pipe_too_big:
        return 0.0, out, 0, print_error(ErrorCode.PIPE_DIAMETER)

    if (is_diaphragm(tip) and d_orif_t < 12.5) or (tip == DeviceType.VENTURI_NOZZLE and d_orif_t <= 50):
        return 0.0, out, 0, print_error(ErrorCode.ORIFICE_DIAMETER)

    beta = d_orif_t / d_pipe_t

    beta_bad = (
        ((beta < 0.23  or beta > 0.80) and tip == DeviceType.ORIFICE_CORNER) or
        ((beta < 0.20  or beta > 0.75) and tip in (DeviceType.ORIFICE_FLANGE, DeviceType.ORIFICE_DD2)) or
        ((beta < 0.30  or beta > 0.80) and tip == DeviceType.NOZZLE_ISA) or
        ((beta < 0.20  or beta > 0.80) and tip == DeviceType.NOZZLE_LONG_RADIUS) or
        ((beta < 0.30  or beta > 0.75) and tip == DeviceType.VENTURI_ROUGH_CAST) or
        ((beta < 0.40  or beta > 0.75) and tip == DeviceType.VENTURI_MACHINED) or
        ((beta < 0.40  or beta > 0.70) and tip == DeviceType.VENTURI_WELDED_SHEET) or
        ((beta < 0.316 or beta > 0.775) and tip == DeviceType.VENTURI_NOZZLE)
    )
    if beta_bad:
        return 0.0, out, 0, print_error(ErrorCode.THROTTLE_RATIO)

    # Expansibility factor ε
    if is_diaphragm(tip):
        expand_fact = 1.0 - (0.41 + 0.35 * beta ** 4) * dp / p / kappa
    else:
        pr = 1.0 - dp / p
        exp2k   = 2.0 / kappa
        expkm1  = (kappa - 1.0) / kappa
        b4      = beta ** 4
        y_k     = pr ** exp2k
        expand_fact = math.sqrt(kappa * y_k / (kappa - 1.0)
                                * (1.0 - b4) / (1.0 - b4 * y_k)
                                * (1.0 - pr ** expkm1) / (1.0 - pr))

    if not math.isfinite(expand_fact) or expand_fact <= 0.0:
        return 0.0, out, 0, print_error(ErrorCode.NUMERIC)

    d_pipe_m  = d_pipe_t / 1000.0
    d_orif_m  = d_orif_t / 1000.0

    reynolds  = INITIAL_REYNOLDS
    qm_curr = qm_prev = 0.0
    converged = False
    n_iter    = 0
    for n_iter in range(1, MAX_REYNOLDS_ITER + 1):
        qm_prev  = qm_curr
        vel_coef = velocity_coefficient(tip, d_pipe_m, beta, reynolds)
        qm_curr  = vel_coef * expand_fact * PI / 4.0 * d_orif_m ** 2 * math.sqrt(FACTOR_2KPA * dp * ro)
        reynolds = 4.0 * qm_curr / (d_pipe_m * PI * eta)
        if not (math.isfinite(vel_coef) and math.isfinite(qm_curr) and math.isfinite(reynolds)):
            return 0.0, out, n_iter, print_error(ErrorCode.NUMERIC)
        denom = max(qm_curr, 1e-10)
        if abs((qm_curr - qm_prev) / denom) <= REYNOLDS_TOLERANCE:
            converged = True
            break

    if not converged:
        return 0.0, out, n_iter, print_error(ErrorCode.NUMERIC)

    # Reynolds validity
    valid = False
    if tip == DeviceType.ORIFICE_CORNER:
        valid = ((5000  <= reynolds <= 1e8 and 0.23 <= beta < 0.45) or
                 (10000 <= reynolds <= 1e8 and 0.45 <= beta < 0.77) or
                 (20000 <= reynolds <= 1e8 and 0.77 <= beta <= 0.80))
    elif tip in (DeviceType.ORIFICE_FLANGE, DeviceType.ORIFICE_DD2):
        valid = (1.26e6 * beta * beta * d_pipe_m <= reynolds <= 1e8)
    elif tip == DeviceType.NOZZLE_ISA:
        valid = ((70000 <= reynolds <= 1e7 and 0.30 <= beta < 0.44) or
                 (20000 <= reynolds <= 1e7 and 0.44 <= beta <= 0.80))
    elif tip == DeviceType.NOZZLE_LONG_RADIUS:
        valid = (10000 <= reynolds <= 1e7)
    elif tip in (DeviceType.VENTURI_ROUGH_CAST, DeviceType.VENTURI_WELDED_SHEET):
        valid = (200000 <= reynolds <= 2000000)
    elif tip == DeviceType.VENTURI_MACHINED:
        valid = (200000 <= reynolds <= 1000000)
    elif tip == DeviceType.VENTURI_NOZZLE:
        valid = (150000 <= reynolds <= 2000000)

    if not valid:
        return 0.0, out, n_iter, print_error(ErrorCode.REYNOLDS, reynolds)

    out.m_velocity    = 4.0 * qm_curr / PI / d_pipe_m / d_pipe_m / ro
    out.m_beta        = beta
    out.m_reynolds    = reynolds
    out.m_coefC       = discharge_coefficient(tip, d_pipe_m, beta, reynolds)
    out.m_epsilon     = expand_fact
    out.m_dWorkingMm  = d_orif_m * 1000.0
    out.m_DWorkingMm  = d_pipe_m * 1000.0
    out.m_kappa       = kappa

    # Permanent pressure loss — ISO 5167-4 Table 1 fixed fractions for Venturi tubes;
    # Idelchik formula for orifice plates and nozzles.
    if tip == DeviceType.VENTURI_ROUGH_CAST:
        loss_frac = 0.15   # ISO 5167-4: 0.15 ± 0.01 for rough-cast convergent
    elif tip == DeviceType.VENTURI_MACHINED:
        loss_frac = 0.08   # ISO 5167-4: 0.08 ± 0.01 for machined convergent
    elif tip == DeviceType.VENTURI_WELDED_SHEET:
        loss_frac = 0.15   # ISO 5167-4: 0.15 for rough-welded sheet-metal convergent
    else:
        c = out.m_coefC
        b2 = beta * beta
        sq = math.sqrt(1.0 - b2 * b2 * (1.0 - c * c))
        loss_frac = (sq - c * b2) / (sq + c * b2)
    out.m_pressureLoss = loss_frac * dp

    return qm_curr, out, n_iter, ""

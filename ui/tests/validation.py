import sys
import os
import io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from constants import (
    NUM_COMPONENTS, ARRAY_SIZE, KPA_PER_ATM, PA_TO_MICRO_PA, SECONDS_PER_HOUR,
    GAS_CONSTANT_R, KELVIN_OFFSET,
    COLOR_YELLOW, COLOR_BOLD_WHITE, COLOR_BOLD_GREEN, COLOR_BOLD_RED, COLOR_RESET,
)
from models import DeviceType, FlowResult
from data.components import MOLAR_MASS_TABLE
from formulas.bwrs import calc_bwr_mixture, calc_density, calc_mixture_thermo
from formulas.viscosity import calc_viscosity
from standards.iso5167 import calc_mass_flow


def run_validation_test():
    print(f"\n{COLOR_YELLOW}  ── Implementation validation test{COLOR_RESET}")

    n_pass  = 0
    n_total = 0

    def chk(label, v, lo, hi, src):
        nonlocal n_pass, n_total
        n_total += 1
        ok = lo <= v <= hi
        if ok:
            n_pass += 1
        pad = max(0, 54 - len(label))
        ivl = f"[{lo:.4f}, {hi:.4f}]"
        status = f"{COLOR_BOLD_GREEN}PASS" if ok else f"{COLOR_BOLD_RED}FAIL"
        print(f"    {COLOR_BOLD_WHITE}{label}" + " " * pad
              + f"{COLOR_BOLD_GREEN}{v:<10.5f}{COLOR_RESET}  {ivl:<24}  {status}{COLOR_RESET}"
              + f"  {COLOR_BOLD_WHITE}[{src}]{COLOR_RESET}")

    def x_pure(idx):
        x = [0.0] * ARRAY_SIZE
        x[idx] = 1.0
        return x

    def test_comp(name, xc, rho20_lo, rho20_hi, rho0_lo, rho0_hi,
                  eta_lo, eta_hi, D_mm, d_mm, p_kpa, dp_kpa, leading_nl=True):
        if leading_nl:
            print()
        print(f"  {COLOR_YELLOW}» {name}{COLOR_RESET}")

        bt = calc_bwr_mixture(xc)
        thermo = calc_mixture_thermo(xc, bt)

        rho1, _ = calc_density(20.0, 1.0, bt)
        rho2, _ = calc_density( 0.0, 1.0, bt)
        chk(f"Density ρ 20°C, 101.325 kPa [kg/m³]", rho1, rho20_lo, rho20_hi, "BWRS 1973")
        chk(f"Density ρ  0°C, 101.325 kPa [kg/m³]", rho2, rho0_lo,  rho0_hi,  "BWRS 1973")
        eta1 = calc_viscosity(20.0, rho1, xc, thermo.m_rocCrit, thermo.m_csi) * PA_TO_MICRO_PA
        chk(f"Viscosity η 20°C, 101.325 kPa [μPa·s]", eta1, eta_lo, eta_hi, "CE/NIST")

        z1 = 1.0 * bt.m_molarMass / (rho1 * GAS_CONSTANT_R * (20.0 + KELVIN_OFFSET))
        chk("Compressibility factor Z 20°C, 101.325 kPa [-]", z1, 0.975, 1.003, "BWRS/ideal")

        mx = sum(xc[i] * MOLAR_MASS_TABLE[i] for i in range(1, NUM_COMPONENTS + 1))
        chk("Molar mass M [g/mol]", bt.m_molarMass, mx * (1 - 1e-8), mx * (1 + 1e-8), "mixing rule")

        if d_mm > 0.0:
            import math
            rho_f, _ = calc_density(20.0, p_kpa / KPA_PER_ATM, bt)
            eta_f    = calc_viscosity(20.0, rho_f, xc, thermo.m_rocCrit, thermo.m_csi)
            A_o      = math.pi / 4.0 * (d_mm * 1e-3) ** 2

            devices = [
                (DeviceType.ORIFICE_CORNER,      "Dia-U",   0.609, 0.993),
                (DeviceType.ORIFICE_FLANGE,      "Dia-F",   0.608, 0.993),
                (DeviceType.ORIFICE_DD2,         "Dia-D/2", 0.608, 0.993),
                (DeviceType.NOZZLE_ISA,          "Aj-ISA",  0.997, 0.997),
                (DeviceType.NOZZLE_LONG_RADIUS,  "Aj-RL",   1.005, 0.997),
                (DeviceType.VENTURI_ROUGH_CAST,  "Ven-B",   0.997, 0.997),
                (DeviceType.VENTURI_MACHINED,    "Ven-P",   1.008, 0.997),
                (DeviceType.VENTURI_WELDED_SHEET,"Ven-T",   0.998, 0.997),
                (DeviceType.VENTURI_NOZZLE,      "Aj-V",    0.996, 0.997),
            ]
            qm_diau = 0.0
            # Suppress ISO 5167 error messages during flow tests
            old_stdout = sys.stdout
            for tip, abv, alpha_nom, eps_nom in devices:
                sys.stdout = io.StringIO()
                qm_f, fr, _, _ = calc_mass_flow(dp_kpa, p_kpa, 20.0, tip, D_mm, d_mm, rho_f, eta_f)
                sys.stdout = old_stdout
                if tip == DeviceType.ORIFICE_CORNER:
                    qm_diau = qm_f
                if qm_f > 0.0:
                    qm_est = alpha_nom * eps_nom * A_o * math.sqrt(2000.0 * dp_kpa * rho_f)
                    lbl = f"Qm D={D_mm},d={d_mm},p={p_kpa},Δp={dp_kpa} {abv} [kg/s]"
                    chk(lbl, qm_f, qm_est * 0.85, qm_est * 1.15, "ISO 5167")
                else:
                    n_total += 1
                    print(f"    {COLOR_BOLD_RED}Qm test {abv}: ISO 5167 ERROR{COLOR_RESET}")
            if qm_diau > 0.0 and rho2 > 0.0:
                qv_n   = qm_diau / rho2 * SECONDS_PER_HOUR
                qm_est = 0.609 * 0.993 * A_o * math.sqrt(2000.0 * dp_kpa * rho_f)
                qv_est = qm_est / rho2 * SECONDS_PER_HOUR
                chk("Volumetric Qv Dia-U, 0°C ref [Nm³/h]",
                    qv_n, qv_est * 0.85, qv_est * 1.15, "ISO 5167/BWRS")

    # Test compositions
    xCH4  = x_pure(1)
    xC2H6 = x_pure(2)
    xCO2  = x_pure(31)
    xH2   = x_pure(24)
    xN2   = x_pure(29)
    xAr   = x_pure(28)

    xGN = [0.0] * ARRAY_SIZE
    xGN[1] = 0.900; xGN[2] = 0.060; xGN[3] = 0.020
    xGN[29] = 0.015; xGN[31] = 0.005

    xGNB = [0.0] * ARRAY_SIZE
    xGNB[1] = 0.850; xGNB[2] = 0.100; xGNB[3] = 0.030
    xGNB[29] = 0.010; xGNB[31] = 0.010

    print(f"\n{COLOR_BOLD_WHITE}  Compositions: ρ(20/0°C), η, Z, M, Qm 9 ISO 5167 types{COLOR_RESET}")

    test_comp("Methane (CH4)",  xCH4,  0.660,1.272, 0.712,0.724, 10.5,12.5, 200,80, 500,5, False)
    test_comp("Ethane (C2H6)", xC2H6, 1.220,1.280, 1.310,1.375,  8.5,10.8, 200,80, 500,5)
    test_comp("CO2",           xCO2,  1.800,1.860, 1.930,2.000, 14.0,16.8, 200,80, 500,5)
    test_comp("Hydrogen (H2)", xH2,   0.082,0.085, 0.088,0.091,  8.2, 9.5, 200,80, 500,5)
    test_comp("Nitrogen (N2)", xN2,   1.155,1.175, 1.240,1.260, 16.5,20.5, 200,80, 500,5)
    test_comp("Argon (Ar)",    xAr,   1.650,1.672, 1.772,1.794, 21.0,23.5, 200,80, 500,5)
    test_comp("Std NG",        xGN,   0.730,0.748, 0.784,0.802, 10.5,12.5, 200,80, 500,5)
    test_comp("Rich NG",       xGNB,  0.765,0.790, 0.820,0.848, 10.2,12.5, 200,80, 500,5)

    # Standalone CH4 monotonicity
    print(f"\n  {COLOR_YELLOW}» Pure CH4 pressure monotonicity{COLOR_RESET}")
    bt_a = calc_bwr_mixture(xCH4)
    rho05, _ = calc_density(20.0,  0.5, bt_a)
    rho10, _ = calc_density(20.0,  1.0, bt_a)
    rho20a, _ = calc_density(20.0, 20.0, bt_a)
    chk("Monotone ρ(1atm)/ρ(0.5atm) CH4 [-]", rho10 / rho05, 1.90, 2.10, "ideal gas")
    chk("Monotone ρ(20atm)/ρ(1atm) CH4 [-]",  rho20a / rho10, 17.0, 23.0, "ideal gas×Z")
    z_hi = 20.0 * bt_a.m_molarMass / (rho20a * GAS_CONSTANT_R * (20.0 + KELVIN_OFFSET))
    chk("Z factor CH4 20°C, 20 atm [-]", z_hi, 0.88, 0.98, "BWRS/NIST")

    # Negative ISO 5167 tests
    print(f"\n  {COLOR_YELLOW}» ISO 5167 negative tests (expect Qm=0){COLOR_RESET}")
    bt_n   = calc_bwr_mixture(xCH4)
    rho_n, _ = calc_density(20.0, 500.0 / KPA_PER_ATM, bt_n)
    eta_n  = 11.5e-6
    old_out = sys.stdout
    sys.stdout = io.StringIO()
    qn = []
    for tip, D, d in [
        (DeviceType.ORIFICE_CORNER,      200, 170),  # β=0.85
        (DeviceType.ORIFICE_CORNER,       30,  15),  # D=30<50
        (DeviceType.VENTURI_MACHINED,    200,  60),  # β=0.30
        (DeviceType.VENTURI_WELDED_SHEET,200, 150),  # β=0.75
        (DeviceType.ORIFICE_CORNER,      200,  10),  # d=10<12.5
        (DeviceType.ORIFICE_CORNER,      200,  44),  # β=0.22
        (DeviceType.ORIFICE_FLANGE,      800, 400),  # D=800>760
        (DeviceType.NOZZLE_ISA,          550, 220),  # D=550>500
        (DeviceType.VENTURI_NOZZLE,      200,  50),  # d=50≤50
    ]:
        q, _, _, _ = calc_mass_flow(5.0, 500.0, 20.0, tip, D, d, rho_n, eta_n)
        qn.append(q)
    sys.stdout = old_out
    labels = [
        "β=0.85 Dia-U (max 0.80) → Qm=0",
        "D=30mm Dia-U (min 50mm) → Qm=0",
        "β=0.30 Ven-P (min 0.40) → Qm=0",
        "β=0.75 Ven-T (max 0.70) → Qm=0",
        "d=10mm Dia-U (min 12.5mm) → Qm=0",
        "β=0.22 Dia-U (min 0.23) → Qm=0",
        "D=800mm Dia-F (max 760mm) → Qm=0",
        "D=550mm Aj-ISA (max 500mm) → Qm=0",
        "d=50mm Aj-V (limit d>50mm) → Qm=0",
    ]
    for label, q in zip(labels, qn):
        chk(label, q, -0.001, 0.001, "ISO 5167")

    # Viscosity monotonicity vs T
    print(f"\n  {COLOR_YELLOW}» Viscosity monotonicity vs T (CH4){COLOR_RESET}")
    bt_mt  = calc_bwr_mixture(xCH4)
    th_mt  = calc_mixture_thermo(xCH4, bt_mt)
    rho_n10, _ = calc_density(-10.0, 1.0, bt_mt)
    rho_p20, _ = calc_density( 20.0, 1.0, bt_mt)
    rho_p60, _ = calc_density( 60.0, 1.0, bt_mt)
    e_n10 = calc_viscosity(-10.0, rho_n10, xCH4, th_mt.m_rocCrit, th_mt.m_csi) * PA_TO_MICRO_PA
    e_p20 = calc_viscosity( 20.0, rho_p20, xCH4, th_mt.m_rocCrit, th_mt.m_csi) * PA_TO_MICRO_PA
    e_p60 = calc_viscosity( 60.0, rho_p60, xCH4, th_mt.m_rocCrit, th_mt.m_csi) * PA_TO_MICRO_PA
    chk("Monotone η(60°C)/η(-10°C) CH4 [-]", e_p60 / e_n10, 1.05, 1.25, "CE/kinetic")
    chk("Monotone η(20°C)/η(-10°C) CH4 [-]", e_p20 / e_n10, 1.01, 1.10, "CE/kinetic")
    chk("Monotone η(60°C)/η(20°C)  CH4 [-]", e_p60 / e_p20, 1.01, 1.12, "CE/kinetic")

    # Viscosity ordering
    print(f"\n  {COLOR_YELLOW}» Viscosity ordering at 20°C, 1 atm{COLOR_RESET}")
    def eta20(xc):
        bt = calc_bwr_mixture(xc)
        th = calc_mixture_thermo(xc, bt)
        ro20, _ = calc_density(20.0, 1.0, bt)
        return calc_viscosity(20.0, ro20, xc, th.m_rocCrit, th.m_csi) * PA_TO_MICRO_PA
    e_ch4 = eta20(xCH4)
    e_n2  = eta20(xN2)
    e_co2 = eta20(xCO2)
    chk("Ordering: η(N2)/η(CH4) at 20°C [-]",  e_n2  / e_ch4, 1.40, 1.80, "CE/NIST")
    chk("Ordering: η(CO2)/η(CH4) at 20°C [-]", e_co2 / e_ch4, 1.20, 1.55, "CE/NIST")

    # Summary
    color = COLOR_BOLD_GREEN if n_pass == n_total else COLOR_BOLD_RED
    print(f"\n  {color}Overall result: {n_pass}/{n_total} tests passed.{COLOR_RESET}")
    if n_pass < n_total:
        print(f"  {COLOR_BOLD_RED}WARNING: Some tests failed — check the implementation!{COLOR_RESET}")
    print(f"\n  {COLOR_BOLD_WHITE}Press any key to continue...{COLOR_RESET}", end="")
    sys.stdout.flush()
    import ui.console
    ui.console.wait_key()
    print()

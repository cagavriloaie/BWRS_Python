# BWRS Gas Flow Calculator

**v3.0 / 2026 · Constantin Agavriloaie · ELCOST Impex · Cluj-Napoca, Romania**

A Python engineering tool for calculating natural-gas mass flow rate through differential-pressure flow devices (orifice plates, nozzles, Venturi tubes), using the Benedict-Webb-Rubin-Starling equation of state.

---

## Features

- **Gas-phase density** via the BWRS equation of state (Starling 1973) with quadratic and cubic mixing rules for 35 components
- **Dynamic viscosity** via the Chapman-Enskog dilute-gas model with Nishiumi-Saito high-density correction
- **Mass flow rate** via ISO 5167-2/3/4:2003 Reynolds iteration (Reader-Harris/Gallagher discharge coefficient)
- **Calorific values, Wobbe index** per ISO 6976:2016 (HHV, LHV at 0 °C / 15 °C / 20 °C)
- **Compressibility factor Z**, speed of sound, Mach number, permanent pressure loss
- **Volumetric flow** at reference conditions: Romania/EU (DIN 1343), ISO 13443, AGA-3, GOST 30319-1, or custom
- **Thermal expansion correction** for pipe (carbon steel) and orifice (stainless steel) diameters
- Built-in **validation test suite** checked against NIST WebBook, AGA-8, and ISO 5167 reference data

---

## Supported flow devices (ISO 5167)

| # | Device | β range |
|---|--------|---------|
| 1 | Orifice plate — corner taps | 0.23 – 0.80 |
| 2 | Orifice plate — flange taps | 0.20 – 0.75 |
| 3 | Orifice plate — D and D/2 taps | 0.20 – 0.75 |
| 4 | ISA 1932 nozzle | 0.30 – 0.80 |
| 5 | Long-radius nozzle | 0.20 – 0.80 |
| 6 | Classical Venturi — rough-cast convergent | 0.30 – 0.75 |
| 7 | Classical Venturi — machined convergent | 0.40 – 0.75 |
| 8 | Classical Venturi — welded sheet-metal convergent | 0.40 – 0.70 |
| 9 | Venturi nozzle | 0.316 – 0.775 |

---

## Gas components (35 total)

**Hydrocarbons:** CH₄, C₂H₆, C₃H₈, i-C₄, n-C₄, neopentane, i-C₅, n-C₅, 2,2-dimethylbutane, 2,3-dimethylbutane, 3-methylpentane, 2-methylpentane, n-C₆, 2,4-dimethylpentane, 2,2,3-trimethylbutane, 2-methylhexane, 3-methylhexane, 3-ethylpentane, n-C₇, 2,2,4-trimethylpentane, n-C₈, benzene, toluene

**Other:** H₂, CO, H₂S, He, Ar, N₂, O₂, CO₂, C₂H₄, C₃H₆, NH₃, C₂H₂

---

## Requirements

- Python 3.9 or later
- Standard library only — no third-party packages required (`tkinter`, `math`, `json`, `threading`, …)

---

## Installation

```bash
git clone https://github.com/cagavriloaie/BWRS_Python.git
cd BWRS_Python
python main_gui.py
```

---

## Usage

### GUI

```bash
python main_gui.py
```

The application opens with five tabs:

1. **Composition** — Enter the 35 molar fractions (sum must equal 1.000). Use *Load* / *Save* / *Normalize* as needed. Click **Apply composition** to compute BWRS mixture constants.
2. **Device** — Select the throttling device type; enter pipe diameter D and orifice diameter d (both at 20 °C). Choose the volumetric reference condition standard.
3. **Conditions** — Enter temperature [°C], absolute pressure [kPa], and differential pressure [kPa]. Click **CALCULATE**.
4. **Results** — View the full calculation report. Copy to clipboard or save as `.txt`.
5. **Tests** — Run the built-in validation suite and review PASS/FAIL results with reference sources.

### Saved state

On first run, `bwrs_comp.json` and `bwrs_conf.json` are created in the working directory and loaded automatically on subsequent starts. The default composition is a representative Romanian natural gas mixture.

---

## Project structure

```
BWRS_Python/
├── main_gui.py              # Entry point (GUI)
├── constants.py             # Physical constants, tolerances, ANSI colours
├── models.py                # Dataclasses and enums
├── data/
│   └── components.py        # BWRS, viscosity, calorific lookup tables (35 components)
├── formulas/
│   ├── bwrs.py              # BWRS EOS — mixing rules, density solver, κ
│   └── viscosity.py         # Chapman-Enskog + Nishiumi-Saito viscosity
├── standards/
│   └── iso5167.py           # Discharge coefficient, expansibility, Reynolds iteration
├── ui/
│   ├── gui.py               # tkinter GUI (BwrsApp, 5 tabs)
│   ├── console.py           # Console key-wait helper
│   └── tests/
│       └── validation.py    # Validation test suite
├── bwrs_comp.json           # Default gas composition (Romanian natural gas)
├── bwrs_conf.json           # Default device configuration
└── BWRS_Calculator.spec     # PyInstaller build specification
```

---

## Building a standalone executable

```bash
pip install pyinstaller
pyinstaller BWRS_Calculator.spec
```

The executable is written to `dist/BWRS_Calculator.exe`. Place `bwrs_comp.json` and `bwrs_conf.json` alongside the `.exe` for persistent composition and configuration.

---

## Calculation models

### BWRS equation of state
11-parameter Benedict-Webb-Rubin-Starling form with Starling (1973) mixing rules:
- Quadratic mixing rules (N²) for A₀, B₀, C₀, D₀, E₀, γ
- Cubic mixing rules (N³) for a, b, c, d, α

Density is solved by a hybrid bisection + Newton-Raphson scheme (up to 200 iterations, relative tolerance 10⁻⁶).

### Viscosity
Chapman-Enskog kinetic-theory dilute-gas model combined with the Nishiumi-Saito (1975) high-density correction:

> Nishiumi, H. & Saito, S., *J. Chem. Eng. Japan* **8**(5), 356–360 (1975).

### ISO 5167 discharge coefficient
Reader-Harris / Gallagher correlation per ISO 5167-2/3/4:2003. Mass flow is obtained by iterating on the Reynolds number until convergence (tolerance 10⁻⁶, up to 100 iterations). The expansibility factor ε uses the exact isentropic formula for nozzles and Venturi tubes, and the ISO 5167-2 linear approximation for orifice plates.

### Isentropic exponent κ
Calculated from the ideal-gas heat capacity Cp° of the mixture at 20 °C:
κ = Cp° / (Cp° − R)

### Calorific values
Molar HHV and LHV per component from ISO 6976:2016, mixed by molar fractions and converted to MJ/kg and MJ/m³ using ideal-gas reference volumes (ISO 6976:2016 §5).

---

## Standards and references

| Standard | Description |
|----------|-------------|
| ISO 5167-1:2003 | Measurement of fluid flow — General principles and requirements |
| ISO 5167-2:2003 | Orifice plates |
| ISO 5167-3:2003 | Nozzles and Venturi nozzles |
| ISO 5167-4:2003 | Classical Venturi tubes |
| ISO 6976:2016 | Natural gas — Calorific values, density, relative density, Wobbe indices |
| ISO 13443:1996 | Natural gas — Standard reference conditions |
| DIN 1343:1990 | Reference conditions for gases |
| AGA Report No. 3 | Orifice metering of natural gas (USA, 60 °F reference) |
| GOST 30319-1 | Flow measurement of natural gas (Russia, 20 °C reference) |
| Starling 1973 | BWRS EOS constants — *Fluid Thermodynamic Properties for Light Petroleum Systems*, Gulf Publishing |
| Nishiumi 1975 | High-density viscosity correction — *J. Chem. Eng. Japan* 8(5) |

---

## License

© 2004–2026 ELCOST Impex. All rights reserved.

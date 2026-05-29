"""tkinter GUI — BWRS Gas Flow Calculator."""
import sys
import os
import math
import json
import re
import io
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, scrolledtext, filedialog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (
    ARRAY_SIZE, NUM_COMPONENTS, KPA_PER_ATM, GAS_CONSTANT_R, KELVIN_OFFSET,
    SUM_TOLERANCE, PA_TO_MICRO_PA, SECONDS_PER_HOUR, REF_TEMP_CELSIUS,
    THERMAL_EXP_PIPE, THERMAL_EXP_ORIFICE, MOLAR_MASS_AIR,
    MOLAR_VOL_0C, MOLAR_VOL_15C, MOLAR_VOL_20C, KJ_PER_MJ, MJ_PER_KWH,
)
from models import DeviceType, CountryRef, TIP_MIN, TIP_MAX, tip_name
from data.components import COMP_NAMES, HHV_TABLE, LHV_TABLE
from formulas.bwrs import calc_bwr_mixture, calc_density, calc_mixture_thermo, calc_kappa
from formulas.viscosity import calc_viscosity
from standards.iso5167 import calc_mass_flow

COMP_FILE = "bwrs_comp.json"
CONF_FILE = "bwrs_conf.json"

DEVICE_NAMES = [tip_name(DeviceType(i)) for i in range(TIP_MIN, TIP_MAX + 1)]

REF_OPTIONS = [
    ("Romania / EU  (DIN 1343)  —  0°C and 15°C",  2, [0.0,  15.0],  ["Nm³/h", "Sm³/h"]),
    ("ISO 13443 / UK / Italy    —  15°C",           1, [15.0,  0.0],  ["Sm³/h", ""]),
    ("USA — AGA-3  (60°F)       —  15.56°C",        1, [15.56, 0.0],  ["Sm³/h", ""]),
    ("Russia — GOST 30319-1     —  20°C",           1, [20.0,  0.0],  ["m³/h",  ""]),
    ("Custom",                                       1, [0.0,   0.0],  ["m³/h",  ""]),
]

PALETTE = {
    "bg":         "#f1f5f9",   # slate-100
    "panel":      "#ffffff",
    "accent":     "#1d4ed8",   # blue-700
    "accent_dk":  "#1e3a8a",   # blue-900
    "accent_lt":  "#eff6ff",   # blue-50
    "header_bg":  "#0f172a",   # slate-900
    "header_fg":  "#f8fafc",   # slate-50
    "header_sub": "#94a3b8",   # slate-400
    "accent_bar": "#2563eb",   # blue-600
    "text":       "#0f172a",   # slate-900
    "muted":      "#64748b",   # slate-500
    "border":     "#cbd5e1",   # slate-300
    "border_lt":  "#e2e8f0",   # slate-200
    "success":    "#059669",   # emerald-600
    "danger":     "#dc2626",   # red-600
    "tab_bg":     "#dde3ed",
    "dark_bg":    "#1a1b26",
    "dark_fg":    "#c0caf5",
}


class _ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0,
                                 bg=PALETTE["bg"])
        sb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self.inner = ttk.Frame(self._canvas)
        self.inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._win = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._canvas.configure(yscrollcommand=sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind("<Enter>", self._bind_mousewheel)
        self._canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._win, width=event.width)

    def _bind_mousewheel(self, _):
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _):
        self._canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")


class BwrsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BWRS Gas Flow Calculator v3.0/2026 — ELCOST Impex")
        self.geometry("1000x740")
        self.minsize(840, 580)

        # Calculation state
        self.x = [0.0] * ARRAY_SIZE
        self.bwr = None
        self.kappa_mix = 0.0
        self.thermo = None

        # --- StringVars ---
        self.comp_vars  = [tk.StringVar(value="0.0") for _ in range(ARRAY_SIZE)]
        self.tip_idx    = tk.IntVar(value=0)
        self.d_int_var  = tk.StringVar()
        self.d_orif_var = tk.StringVar()
        self.beta_var   = tk.StringVar(value="—")
        self.ref_sel    = tk.IntVar(value=1)
        self.custom_t   = tk.StringVar(value="20.0")
        self.temp_var   = tk.StringVar()
        self.press_var  = tk.StringVar()
        self.dp_var     = tk.StringVar()

        self._setup_styles()
        self._build_ui()
        self._try_load_composition()
        self._try_load_config()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _setup_styles(self):
        P = PALETTE
        style = ttk.Style(self)

        for preferred in ("clam", "alt", "default"):
            if preferred in style.theme_names():
                style.theme_use(preferred)
                break

        self.configure(bg=P["bg"])

        # Notebook
        style.configure("TNotebook", background=P["bg"], borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=P["tab_bg"],
                        foreground=P["text"],
                        padding=[22, 10],
                        font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", P["accent"]), ("active", P["accent_lt"])],
                  foreground=[("selected", "white"), ("active", P["accent_dk"])])

        # Frames
        style.configure("TFrame", background=P["bg"])

        # LabelFrame — card style with solid border
        style.configure("TLabelframe",
                        background=P["bg"],
                        bordercolor=P["border"],
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label",
                        background=P["bg"],
                        foreground=P["accent"],
                        font=("Segoe UI", 10, "bold"),
                        padding=(6, 2))

        # Labels
        style.configure("TLabel",
                        background=P["bg"],
                        foreground=P["text"],
                        font=("Segoe UI", 10))
        style.configure("Muted.TLabel",
                        background=P["bg"],
                        foreground=P["muted"],
                        font=("Segoe UI", 9))

        # Primary button
        style.configure("TButton",
                        background=P["accent"],
                        foreground="white",
                        padding=[14, 7],
                        font=("Segoe UI", 10, "bold"),
                        relief="flat", borderwidth=0)
        style.map("TButton",
                  background=[("active", P["accent_dk"]), ("disabled", "#9ca3af")],
                  foreground=[("disabled", "#e5e7eb")],
                  relief=[("pressed", "flat"), ("active", "flat")])

        # Large CALCULATE button
        style.configure("Calc.TButton",
                        background=P["accent"],
                        foreground="white",
                        padding=[20, 12],
                        font=("Segoe UI", 12, "bold"),
                        relief="flat", borderwidth=0)
        style.map("Calc.TButton",
                  background=[("active", P["accent_dk"]), ("disabled", "#9ca3af")],
                  foreground=[("disabled", "#e5e7eb")],
                  relief=[("pressed", "flat"), ("active", "flat")])

        # Secondary / ghost button
        style.configure("Sec.TButton",
                        background=P["border_lt"],
                        foreground=P["text"],
                        padding=[10, 6],
                        font=("Segoe UI", 10),
                        relief="flat", borderwidth=0)
        style.map("Sec.TButton",
                  background=[("active", P["border"])],
                  relief=[("pressed", "flat"), ("active", "flat")])

        # Entry / Combobox
        style.configure("TEntry",
                        fieldbackground=P["panel"],
                        foreground=P["text"],
                        font=("Segoe UI", 10),
                        padding=[6, 5])
        style.configure("TCombobox",
                        fieldbackground=P["panel"],
                        foreground=P["text"],
                        font=("Segoe UI", 10),
                        padding=[4, 4])

        # Radiobutton
        style.configure("TRadiobutton",
                        background=P["bg"],
                        foreground=P["text"],
                        font=("Segoe UI", 10))
        style.map("TRadiobutton", background=[("active", P["bg"])])

        # Scrollbar
        style.configure("TScrollbar",
                        background=P["border"],
                        troughcolor=P["bg"])

        # Separator
        style.configure("TSeparator", background=P["border_lt"])

        # Progress bar (composition sum indicator)
        style.configure("Sum.Horizontal.TProgressbar",
                        troughcolor=P["border_lt"],
                        background=P["accent"],
                        darkcolor=P["accent"],
                        lightcolor=P["accent"],
                        bordercolor=P["border_lt"],
                        thickness=6)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_statusbar()   # reserve bottom strip before notebook

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        tabs = [
            ("  Composition ", self._build_composition_tab),
            ("  Device      ", self._build_device_tab),
            ("  Conditions  ", self._build_conditions_tab),
            ("  Results     ", self._build_results_tab),
            ("  Tests       ", self._build_test_tab),
        ]
        for title, builder in tabs:
            frame = ttk.Frame(self.nb)
            self.nb.add(frame, text=title)
            builder(frame)

    def _build_header(self):
        P = PALETTE
        hdr = tk.Frame(self, bg=P["header_bg"], height=68)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)

        # Left accent stripe
        tk.Frame(hdr, bg=P["accent_bar"], width=4).pack(side=tk.LEFT, fill=tk.Y)

        # App icon
        tk.Label(hdr, text="⊕",
                 bg=P["header_bg"], fg=P["accent_bar"],
                 font=("Segoe UI", 22)).pack(side=tk.LEFT, padx=(14, 6), fill=tk.Y)

        # Title block
        inner = tk.Frame(hdr, bg=P["header_bg"])
        inner.pack(side=tk.LEFT, fill=tk.Y, pady=12)
        tk.Label(inner,
                 text="BWRS Gas Flow Calculator",
                 bg=P["header_bg"], fg=P["header_fg"],
                 font=("Segoe UI", 15, "bold"),
                 anchor="w").pack(anchor="w")
        tk.Label(inner,
                 text="BWRS  ·  ISO 5167  ·  ISO 6976:2016  ·  v3.0 / 2026  ·  ELCOST Impex",
                 bg=P["header_bg"], fg=P["header_sub"],
                 font=("Segoe UI", 8),
                 anchor="w").pack(anchor="w")

        # Help button (right side) with hover effect
        right = tk.Frame(hdr, bg=P["header_bg"])
        right.pack(side=tk.RIGHT, padx=20, fill=tk.Y)
        _btn_bg  = "#1e293b"  # slate-800 idle
        _btn_hov = P["accent_bar"]
        help_btn = tk.Button(right,
                             text="  ？  Help  ",
                             bg=_btn_bg, fg=P["header_sub"],
                             font=("Segoe UI", 9),
                             relief="flat", cursor="hand2",
                             activebackground=_btn_hov,
                             activeforeground="white",
                             bd=0, padx=10, pady=7,
                             command=self._show_help)
        help_btn.pack(side=tk.RIGHT, anchor="center")
        help_btn.bind("<Enter>", lambda e: help_btn.config(bg=_btn_hov, fg="white"))
        help_btn.bind("<Leave>", lambda e: help_btn.config(bg=_btn_bg, fg=P["header_sub"]))

        # Accent rule
        tk.Frame(self, bg=P["accent_bar"], height=3).pack(fill=tk.X, side=tk.TOP)

    def _build_statusbar(self):
        P = PALETTE
        tk.Frame(self, bg=P["border_lt"], height=1).pack(fill=tk.X, side=tk.BOTTOM)
        sb = tk.Frame(self, bg=P["panel"], height=30)
        sb.pack(fill=tk.X, side=tk.BOTTOM)
        sb.pack_propagate(False)

        # Coloured status dot
        self._status_dot = tk.Label(sb, text="●",
                                     bg=P["panel"], fg=P["muted"],
                                     font=("Segoe UI", 10), padx=12)
        self._status_dot.pack(side=tk.LEFT)

        self._statusbar_lbl = tk.Label(
            sb, text="Ready.",
            bg=P["panel"], fg=P["muted"],
            font=("Segoe UI", 9), anchor="w")
        self._statusbar_lbl.pack(side=tk.LEFT, fill=tk.Y)

        # Right standards badge
        badge = tk.Frame(sb, bg=P["border_lt"])
        badge.pack(side=tk.RIGHT, padx=12, pady=5)
        tk.Label(badge,
                 text="  ISO 5167  ·  BWRS  ·  ISO 6976:2016  ",
                 bg=P["border_lt"], fg=P["muted"],
                 font=("Segoe UI", 8), padx=4, pady=2).pack()

    def _set_status(self, text: str, kind: str = "normal"):
        P = PALETTE
        palette = {
            "normal": (P["muted"],   P["muted"]),
            "ok":     (P["success"], P["success"]),
            "error":  (P["danger"],  P["danger"]),
        }
        dot_c, txt_c = palette.get(kind, (P["muted"], P["muted"]))
        self._status_dot.config(fg=dot_c)
        self._statusbar_lbl.config(text=text, fg=txt_c)

    # Tab 1 — Composition
    def _build_composition_tab(self, frame):
        bar = ttk.Frame(frame)
        bar.pack(fill=tk.X, padx=12, pady=(10, 2))
        ttk.Label(bar, text="Molar fractions of the gas mixture",
                  font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        for txt, cmd in [("Load", self._load_composition),
                         ("Save", self._save_composition),
                         ("Normalize", self._normalize)]:
            ttk.Button(bar, text=txt, command=cmd,
                       style="Sec.TButton").pack(side=tk.RIGHT, padx=3)

        # Footer (packed before scroll frame so it stays visible)
        footer = ttk.Frame(frame)
        footer.pack(fill=tk.X, padx=12, pady=(4, 2), side=tk.BOTTOM)
        ttk.Label(footer, text="Sum of fractions:",
                  foreground=PALETTE["muted"],
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._sum_lbl = ttk.Label(footer, text="0.000000",
                                   foreground=PALETTE["danger"],
                                   font=("Segoe UI", 12, "bold"))
        self._sum_lbl.pack(side=tk.LEFT, padx=8)
        self._apply_btn = ttk.Button(footer, text="Apply composition  →",
                                      command=self._apply_composition)
        self._apply_btn.pack(side=tk.RIGHT, padx=4)

        # Sum progress bar
        self._sum_bar = ttk.Progressbar(
            frame, orient="horizontal", mode="determinate",
            maximum=1.0, style="Sum.Horizontal.TProgressbar")
        self._sum_bar.pack(fill=tk.X, padx=12, pady=(0, 2), side=tk.BOTTOM)

        # Separator
        ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, padx=12, pady=(4, 0))

        # Scrollable grid
        sf = _ScrollableFrame(frame)
        sf.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        inner = sf.inner
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)

        self._comp_entries = []
        for i in range(1, NUM_COMPONENTS + 1):
            row_idx = (i - 1) // 2
            col_idx = (i - 1) % 2
            cell = ttk.Frame(inner)
            cell.grid(row=row_idx, column=col_idx, sticky="ew", padx=10, pady=3)
            cell.columnconfigure(1, weight=1)
            ttk.Label(cell, text=COMP_NAMES[i], width=22, anchor="w").grid(
                row=0, column=0, sticky="w")
            e = ttk.Entry(cell, textvariable=self.comp_vars[i], width=14)
            e.grid(row=0, column=1, sticky="ew", padx=(6, 0))
            e.bind("<FocusOut>", lambda _ev, _e=e: self._update_sum())
            self._comp_entries.append(e)

    # Tab 2 — Device & diameters & reference
    def _build_device_tab(self, frame):
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        # Left: device + diameters
        lf = ttk.LabelFrame(frame, text="Throttling device")
        lf.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        lf.columnconfigure(1, weight=1)

        ttk.Label(lf, text="Device type:").grid(
            row=0, column=0, sticky="w", padx=12, pady=10)
        self._tip_combo = ttk.Combobox(lf, values=DEVICE_NAMES,
                                        state="readonly", width=38)
        self._tip_combo.current(0)
        self._tip_combo.grid(row=0, column=1, sticky="ew", padx=12, pady=10)

        for r, (lbl, var) in enumerate([
            ("Pipe diameter D  (20°C) [mm]:", self.d_int_var),
            ("Orifice diameter d  (20°C) [mm]:", self.d_orif_var),
        ], start=1):
            ttk.Label(lf, text=lbl).grid(row=r, column=0, sticky="w", padx=12, pady=8)
            e = ttk.Entry(lf, textvariable=var, width=14)
            e.grid(row=r, column=1, sticky="w", padx=12, pady=8)
            e.bind("<FocusOut>", lambda _ev: self._update_beta())

        ttk.Label(lf, text="Ratio β = d / D  (at 20 °C):").grid(
            row=3, column=0, sticky="w", padx=12, pady=8)
        self._beta_lbl = ttk.Label(lf, textvariable=self.beta_var,
                                    font=("Segoe UI", 12, "bold"),
                                    foreground=PALETTE["accent_dk"])
        self._beta_lbl.grid(row=3, column=1, sticky="w", padx=12, pady=8)

        ttk.Separator(lf, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=4)

        ttk.Button(lf, text="Save configuration",
                   command=self._save_config_gui,
                   style="Sec.TButton").grid(
            row=5, column=0, columnspan=2, pady=10)

        self._mix_lbl = ttk.Label(lf, text="", foreground=PALETTE["accent"],
                                   justify=tk.LEFT, font=("Segoe UI", 10))
        self._mix_lbl.grid(row=6, column=0, columnspan=2, sticky="w",
                            padx=12, pady=(0, 10))

        # Right: reference conditions
        rf = ttk.LabelFrame(frame, text="Reference conditions")
        rf.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)

        for i, (name, *_) in enumerate(REF_OPTIONS, start=1):
            ttk.Radiobutton(rf, text=name, variable=self.ref_sel, value=i).pack(
                anchor="w", padx=14, pady=5)

        ttk.Separator(rf, orient="horizontal").pack(fill=tk.X, padx=14, pady=4)
        cust_row = ttk.Frame(rf)
        cust_row.pack(anchor="w", padx=26, pady=4)
        ttk.Label(cust_row, text="Reference temperature [°C]:").pack(side=tk.LEFT)
        ttk.Entry(cust_row, textvariable=self.custom_t, width=8).pack(
            side=tk.LEFT, padx=8)

    # Tab 3 — Conditions + Calculate
    def _build_conditions_tab(self, frame):
        P = PALETTE
        outer = ttk.Frame(frame)
        outer.place(relx=0.5, rely=0.46, anchor="center")

        # White card with top accent stripe and border
        card = tk.Frame(outer, bg=P["panel"],
                        highlightthickness=1, highlightbackground=P["border"])
        card.pack()

        # Top accent stripe
        tk.Frame(card, bg=P["accent"], height=3).pack(fill=tk.X, side=tk.TOP)

        body = tk.Frame(card, bg=P["panel"])
        body.pack(padx=40, pady=(22, 30))
        body.columnconfigure(1, weight=1)

        # Card title
        tk.Label(body, text="Measurement Conditions",
                 bg=P["panel"], fg=P["text"],
                 font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 18))

        fields = [
            ("Temperature",          "°C",  self.temp_var),
            ("Absolute pressure",    "kPa", self.press_var),
            ("Differential pressure","kPa", self.dp_var),
        ]
        for r, (lbl, unit, var) in enumerate(fields, start=1):
            tk.Label(body, text=lbl,
                     bg=P["panel"], fg=P["muted"],
                     font=("Segoe UI", 10), width=24, anchor="e").grid(
                row=r, column=0, padx=(0, 12), pady=9, sticky="e")
            ttk.Entry(body, textvariable=var, width=12,
                      font=("Segoe UI", 13)).grid(
                row=r, column=1, pady=9, ipady=5, sticky="ew")
            tk.Label(body, text=unit,
                     bg=P["panel"], fg=P["muted"],
                     font=("Segoe UI", 10), width=5, anchor="w").grid(
                row=r, column=2, padx=(10, 0), pady=9, sticky="w")

        # Divider
        tk.Frame(body, bg=P["border_lt"], height=1).grid(
            row=len(fields) + 1, column=0, columnspan=3,
            sticky="ew", pady=(12, 0))

        # CALCULATE — full-width, large
        ttk.Button(body, text="  ▶   CALCULATE",
                   command=self._calculate,
                   style="Calc.TButton").grid(
            row=len(fields) + 2, column=0, columnspan=3,
            sticky="ew", pady=(16, 0), ipady=2)

        self._status_lbl = ttk.Label(outer, text="",
                                      foreground=P["danger"],
                                      wraplength=480, justify=tk.CENTER,
                                      font=("Segoe UI", 10))
        self._status_lbl.pack(pady=(10, 0))

    # Tab 4 — Results
    def _build_results_tab(self, frame):
        bar = ttk.Frame(frame)
        bar.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(bar, text="Calculation report",
                  font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=4)
        for txt, cmd in [("Copy to clipboard", self._copy_results),
                         ("Save .txt",          self._save_results)]:
            ttk.Button(bar, text=txt, command=cmd,
                       style="Sec.TButton").pack(side=tk.RIGHT, padx=3)

        ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, padx=8, pady=(0, 4))

        self._results_txt = scrolledtext.ScrolledText(
            frame, wrap=tk.NONE, font=("Courier New", 11),
            state=tk.DISABLED, bg=PALETTE["dark_bg"], fg=PALETTE["dark_fg"],
            insertbackground="white", relief="flat", borderwidth=0,
        )
        self._results_txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        h_sb = ttk.Scrollbar(frame, orient="horizontal",
                              command=self._results_txt.xview)
        h_sb.pack(fill=tk.X, padx=8, side=tk.BOTTOM)
        self._results_txt.configure(xscrollcommand=h_sb.set)

        self._results_txt.tag_config("sep_d",   foreground="#e5c07b")
        self._results_txt.tag_config("sep_s",   foreground="#3e4451")
        self._results_txt.tag_config("title",   foreground="#e5c07b", font=("Courier New", 11, "bold"))
        self._results_txt.tag_config("section", foreground="#61afef")
        self._results_txt.tag_config("label",   foreground="#abb2bf")
        self._results_txt.tag_config("value",   foreground="#98c379")
        self._results_txt.tag_config("unit",    foreground="#5c6370")
        self._results_txt.tag_config("info",    foreground="#d4d4d4")
        self._results_txt.tag_config("note",    foreground="#e5c07b")

    # Tab 5 — Validation tests
    def _build_test_tab(self, frame):
        bar = ttk.Frame(frame)
        bar.pack(fill=tk.X, padx=8, pady=6)
        self._run_test_btn = ttk.Button(bar, text="▶  Run validation tests",
                                         command=self._run_tests)
        self._run_test_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Legend", command=self._populate_test_legend,
                   style="Sec.TButton").pack(side=tk.LEFT, padx=4)
        self._test_summary = ttk.Label(bar, text="", font=("Segoe UI", 12, "bold"))
        self._test_summary.pack(side=tk.LEFT, padx=16)

        ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, padx=8, pady=(0, 4))

        # Color legend
        legend = tk.Frame(frame, bg=PALETTE["dark_bg"], padx=10, pady=5)
        legend.pack(fill=tk.X, padx=8)
        tk.Label(legend, text="Legend: ",
                 bg=PALETTE["dark_bg"], fg=PALETTE["muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        for color, label in [
            ("#4ec94e", "PASS"),
            ("#f04040", "FAIL / ERROR"),
            ("#e5c07b", "Section / Header"),
            ("#61afef", "General result"),
            ("#d4d4d4", "Normal"),
        ]:
            tk.Label(legend, text=f"● {label}   ",
                     bg=PALETTE["dark_bg"], fg=color,
                     font=("Courier New", 9)).pack(side=tk.LEFT)

        self._test_txt = scrolledtext.ScrolledText(
            frame, wrap=tk.NONE, font=("Courier New", 11),
            state=tk.DISABLED, bg=PALETTE["dark_bg"], fg=PALETTE["dark_fg"],
            relief="flat", borderwidth=0,
        )
        self._test_txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
        self._test_txt.tag_config("pass",     foreground="#4ec94e")
        self._test_txt.tag_config("fail",     foreground="#f04040")
        self._test_txt.tag_config("header",   foreground="#e5c07b")
        self._test_txt.tag_config("section",  foreground="#61afef")
        self._test_txt.tag_config("normal",   foreground="#d4d4d4")
        self._test_txt.tag_config("leg_head", foreground="#e5c07b",
                                   font=("Courier New", 11, "bold"))
        self._test_txt.tag_config("leg_sym",  foreground="#56b6c2")
        self._test_txt.tag_config("leg_unit", foreground="#5c6370")
        self._test_txt.tag_config("leg_desc", foreground="#abb2bf")
        self._test_txt.tag_config("leg_key",  foreground="#61afef")
        self._test_txt.tag_config("leg_val",  foreground="#d4d4d4")
        self._populate_test_legend()

    _TEST_LEGEND = (
        ("  Physical quantities:\n",                              "leg_head"),
        ("    ρ",   "leg_sym"), ("   [kg/m³]  ", "leg_unit"), ("  density\n",                          "leg_desc"),
        ("    η",   "leg_sym"), ("   [µPa·s]  ", "leg_unit"), ("  dynamic viscosity\n",                "leg_desc"),
        ("    Z",   "leg_sym"), ("   [-]       ", "leg_unit"), ("  compressibility factor\n",           "leg_desc"),
        ("    M",   "leg_sym"), ("   [g/mol]  ", "leg_unit"), ("  molar mass\n",                       "leg_desc"),
        ("    Qm",  "leg_sym"), ("  [kg/s]    ", "leg_unit"), ("  mass flow rate\n",                   "leg_desc"),
        ("    Qv",  "leg_sym"), ("  [Nm³/h]   ", "leg_unit"), ("  volumetric flow  (0°C, 101.325 kPa)\n", "leg_desc"),
        ("\n", "leg_desc"),
        ("  Flow device parameters:\n",                           "leg_head"),
        ("    D",   "leg_sym"), ("   [mm]      ", "leg_unit"), ("  pipe diameter\n",                   "leg_desc"),
        ("    d",   "leg_sym"), ("   [mm]      ", "leg_unit"), ("  orifice / throat diameter\n",        "leg_desc"),
        ("    β",   "leg_sym"), ("   [-]       ", "leg_unit"), ("  diameter ratio  β = d/D\n",          "leg_desc"),
        ("    p",   "leg_sym"), ("   [kPa]     ", "leg_unit"), ("  absolute pressure\n",               "leg_desc"),
        ("    Δp",  "leg_sym"), ("  [kPa]     ", "leg_unit"), ("  differential pressure\n",            "leg_desc"),
        ("\n", "leg_desc"),
        ("  ISO 5167 devices:\n",                                 "leg_head"),
        ("    Dia-U   ", "leg_key"), (" = ", "leg_desc"), ("Orifice plate, corner taps\n",              "leg_val"),
        ("    Dia-F   ", "leg_key"), (" = ", "leg_desc"), ("Orifice plate, flange taps\n",              "leg_val"),
        ("    Dia-D/2 ", "leg_key"), (" = ", "leg_desc"), ("Orifice plate, D and D/2 taps\n",          "leg_val"),
        ("    Aj-ISA  ", "leg_key"), (" = ", "leg_desc"), ("ISA 1932 nozzle\n",                        "leg_val"),
        ("    Aj-RL   ", "leg_key"), (" = ", "leg_desc"), ("Long-radius nozzle (ASME long-radius)\n",  "leg_val"),
        ("    Ven-B   ", "leg_key"), (" = ", "leg_desc"), ("Venturi tube — rough-cast convergent      (C ≈ 0.984)\n", "leg_val"),
        ("    Ven-P   ", "leg_key"), (" = ", "leg_desc"), ("Venturi tube — machined convergent        (C ≈ 0.995)\n", "leg_val"),
        ("    Ven-T   ", "leg_key"), (" = ", "leg_desc"), ("Venturi tube — welded sheet-metal conv.   (C ≈ 0.985)\n", "leg_val"),
        ("    Aj-V    ", "leg_key"), (" = ", "leg_desc"), ("Venturi nozzle                             (C ≈ 0.983)\n", "leg_val"),
        ("\n", "leg_desc"),
        ("  Reference sources  [right column of each test]:\n",   "leg_head"),
        ("    BWRS 1973     ", "leg_key"), (" = ", "leg_desc"), ("Benedict-Webb-Rubin-Starling (Starling, K.E., 1973)\n",    "leg_val"),
        ("    CE/NIST       ", "leg_key"), (" = ", "leg_desc"), ("Chapman-Enskog + density correction / NIST WebBook\n",     "leg_val"),
        ("    BWRS/ideal    ", "leg_key"), (" = ", "leg_desc"), ("BWRS vs ideal gas at 101.325 kPa\n",                       "leg_val"),
        ("    BWRS/NIST     ", "leg_key"), (" = ", "leg_desc"), ("BWRS compared with NIST WebBook tabulated data\n",         "leg_val"),
        ("    NIST/BWRS     ", "leg_key"), (" = ", "leg_desc"), ("NIST reference, calculated with BWRS\n",                   "leg_val"),
        ("    BWRS/AGA-8    ", "leg_key"), (" = ", "leg_desc"), ("BWRS compared with AGA-8 data\n",                          "leg_val"),
        ("    BWRS/estim.   ", "leg_key"), (" = ", "leg_desc"), ("BWRS compared with engineering estimate\n",                "leg_val"),
        ("    BWRS/Z        ", "leg_key"), (" = ", "leg_desc"), ("ρ monotonicity with Z-factor correction\n",                "leg_val"),
        ("    ISO 5167      ", "leg_key"), (" = ", "leg_desc"), ("ISO 5167-2/3/4:2003 (Reader-Harris/Gallagher)\n",          "leg_val"),
        ("    ISO 5167/BWRS ", "leg_key"), (" = ", "leg_desc"), ("Qv = Qm(ISO 5167) / ρ(BWRS, 0°C, 101.325 kPa)\n",        "leg_val"),
        ("    mixing rule   ", "leg_key"), (" = ", "leg_desc"), ("linear rule  M = Σ xᵢ·Mᵢ\n",                              "leg_val"),
        ("    ideal gas     ", "leg_key"), (" = ", "leg_desc"), ("monotonicity test  ρ(2p)/ρ(p) ≈ 2\n",                     "leg_val"),
        ("    ideal gas×Z   ", "leg_key"), (" = ", "leg_desc"), ("as above, with Z-factor correction\n",                    "leg_val"),
        ("    single-phase  ", "leg_key"), (" = ", "leg_desc"), ("Z ∈ [0.75, 1.02] check (gas phase)\n",                   "leg_val"),
        ("    quasi-ideal   ", "leg_key"), (" = ", "leg_desc"), ("ρ/ρ_ideal ∈ [0.990, 1.025] at p ≤ 500 kPa\n",           "leg_val"),
        ("    monotone T    ", "leg_key"), (" = ", "leg_desc"), ("ρ(T₁) > ρ(T₂) at T₁ < T₂  (density increases with cooling)\n",   "leg_val"),
        ("    monotone P    ", "leg_key"), (" = ", "leg_desc"), ("ρ(p₁) < ρ(p₂) at p₁ < p₂  (density increases with pressure)\n",  "leg_val"),
        ("    M + Z         ", "leg_key"), (" = ", "leg_desc"), ("density ratio ≈ (Mₐ/M_b) × (Z_b/Zₐ)\n",                  "leg_val"),
        ("    CE/kinetic    ", "leg_key"), (" = ", "leg_desc"), ("Chapman-Enskog from kinetic theory (monotone η vs. T)\n", "leg_val"),
        ("\n", "leg_desc"),
    )

    def _populate_test_legend(self):
        w = self._test_txt
        w.config(state=tk.NORMAL)
        w.delete("1.0", tk.END)
        for text, tag in self._TEST_LEGEND:
            w.insert(tk.END, text, tag)
        w.config(state=tk.DISABLED)

    _ANSI_RE = re.compile(r'\033\[[0-9;]*m')

    def _run_tests(self):
        self._run_test_btn.config(state=tk.DISABLED)
        self._test_summary.config(text="Running...", foreground=PALETTE["muted"])
        self._set_status("Running validation tests...", "normal")
        threading.Thread(target=self._tests_worker, daemon=True).start()

    def _tests_worker(self):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            import ui.tests.validation as val
            import ui.console as con
            _orig_wait = con.wait_key
            con.wait_key = lambda: None
            try:
                val.run_validation_test()
            except Exception as exc:
                print(f"\nEroare la rularea testelor: {exc}")
            finally:
                con.wait_key = _orig_wait
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.after(0, self._display_test_output, output)

    def _display_test_output(self, raw: str):
        self._test_txt.config(state=tk.NORMAL)
        self._test_txt.delete("1.0", tk.END)

        n_pass = n_fail = 0
        for line in raw.splitlines():
            clean = self._ANSI_RE.sub("", line)
            if "PASS" in clean:
                tag = "pass";    n_pass += 1
            elif "FAIL" in clean or "ERROR" in clean:
                tag = "fail";    n_fail += 1
            elif clean.strip().startswith("»") or "──" in clean:
                tag = "header"
            elif clean.strip().startswith("Overall") or "tests passed" in clean:
                tag = "section"
            else:
                tag = "normal"
            self._test_txt.insert(tk.END, clean + "\n", tag)

        self._test_txt.config(state=tk.DISABLED)
        total = n_pass + n_fail
        if total > 0:
            if n_fail == 0:
                self._test_summary.config(text=f"{n_pass}/{total} PASS",
                                          foreground=PALETTE["success"])
                self._set_status(f"Tests: {n_pass}/{total} passed.", "ok")
            else:
                self._test_summary.config(text=f"{n_pass}/{total} PASS",
                                          foreground=PALETTE["danger"])
                self._set_status(f"Tests: {n_fail} failed out of {total}.", "error")
        self._run_test_btn.config(state=tk.NORMAL)

    # ── Composition helpers ────────────────────────────────────────────────────

    def _update_sum(self):
        P = PALETTE
        total = 0.0
        for i in range(1, NUM_COMPONENTS + 1):
            try:
                total += float(self.comp_vars[i].get())
            except ValueError:
                pass
        ok = abs(total - 1.0) <= SUM_TOLERANCE
        bar_color = P["success"] if ok else P["danger"]
        self._sum_lbl.config(text=f"{total:.6f}",
                              foreground=bar_color)
        self._sum_bar["value"] = min(max(total, 0.0), 1.0)
        ttk.Style().configure("Sum.Horizontal.TProgressbar",
                               background=bar_color,
                               darkcolor=bar_color,
                               lightcolor=bar_color)

    def _normalize(self):
        vals = []
        for i in range(1, NUM_COMPONENTS + 1):
            try:
                vals.append(float(self.comp_vars[i].get()))
            except ValueError:
                vals.append(0.0)
        total = sum(vals)
        if total < 1e-10:
            messagebox.showerror("Error", "Sum of fractions is zero.")
            return
        for i in range(1, NUM_COMPONENTS + 1):
            self.comp_vars[i].set(f"{vals[i - 1] / total:.8f}")
        self._update_sum()

    def _load_composition(self):
        try:
            with open(COMP_FILE, "r") as f:
                data = json.load(f)
            fracs = data.get("fractions", [])
            if len(fracs) != NUM_COMPONENTS:
                messagebox.showerror("Error", "Invalid composition file.")
                return
            for i, v in enumerate(fracs):
                v = float(v)
                if not (0.0 <= v <= 1.0):
                    messagebox.showerror(
                        "Error",
                        f"Invalid fraction for component {i + 1}: {v} is not in [0, 1]."
                    )
                    return
            for i in range(NUM_COMPONENTS):
                self.comp_vars[i + 1].set(f"{float(fracs[i]):.8f}")
            self._update_sum()
            self._set_status(f"Composition loaded from {COMP_FILE}.", "ok")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _save_composition(self):
        try:
            vals = [float(self.comp_vars[i].get())
                    for i in range(1, NUM_COMPONENTS + 1)]
            with open(COMP_FILE, "w") as f:
                json.dump({"fractions": vals}, f, indent=2)
            messagebox.showinfo("OK", f"Composition saved to {COMP_FILE}")
            self._set_status(f"Composition saved to {COMP_FILE}.", "ok")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _apply_composition(self):
        self._apply_btn.config(text="Applying…", state=tk.DISABLED)
        self.update_idletasks()   # flush redraw so the label change is visible
        try:
            self._do_apply_composition()
        finally:
            self._apply_btn.config(text="Apply composition  →", state=tk.NORMAL)

    def _do_apply_composition(self):
        for i in range(1, NUM_COMPONENTS + 1):
            try:
                v = float(self.comp_vars[i].get())
            except ValueError:
                messagebox.showerror("Error",
                                     f"Invalid value for {COMP_NAMES[i]}")
                return
            if not (0.0 <= v <= 1.0):
                messagebox.showerror("Error",
                                     f"{COMP_NAMES[i]}: fraction must be in [0, 1].")
                return
            self.x[i] = v

        total = sum(self.x[i] for i in range(1, NUM_COMPONENTS + 1))
        if abs(total - 1.0) > SUM_TOLERANCE:
            messagebox.showerror(
                "Error",
                f"Sum of fractions = {total:.6f} ≠ 1.0\n"
                "Normalise or correct the values."
            )
            return

        self.bwr       = calc_bwr_mixture(self.x)
        self.kappa_mix = calc_kappa(self.x)
        self.thermo    = calc_mixture_thermo(self.x, self.bwr)

        rel_d = self.bwr.m_molarMass / MOLAR_MASS_AIR
        self._mix_lbl.config(
            text=f"Molar mass:  {self.bwr.m_molarMass:.4f} g/mol\n"
                 f"Relative density:  {rel_d:.4f}"
        )
        self._set_status(
            f"Composition applied  ·  M = {self.bwr.m_molarMass:.4f} g/mol  ·  d = {rel_d:.4f}",
            "ok"
        )
        messagebox.showinfo(
            "Composition applied",
            f"Molar mass: {self.bwr.m_molarMass:.4f} g/mol\n"
            f"Relative density: {rel_d:.4f}"
        )

    # ── Device helpers ─────────────────────────────────────────────────────────

    def _update_beta(self):
        try:
            d   = float(self.d_int_var.get())
            d_o = float(self.d_orif_var.get())
            if d > 0 and d_o > 0:
                beta = d_o / d
                self.beta_var.set(f"{beta:.4f}")
                in_range = 0.10 <= beta <= 0.80
                self._beta_lbl.config(
                    foreground=PALETTE["accent_dk"] if in_range else PALETTE["danger"])
            else:
                self.beta_var.set("—")
        except ValueError:
            self.beta_var.set("—")

    def _save_config_gui(self):
        try:
            tip_raw = self._tip_combo.current() + TIP_MIN
            d_int   = float(self.d_int_var.get())
            d_orif  = float(self.d_orif_var.get())
            with open(CONF_FILE, "w") as f:
                json.dump({"tip": tip_raw, "d_int": d_int,
                           "d_orif": d_orif}, f, indent=2)
            messagebox.showinfo("OK", f"Configuration saved to {CONF_FILE}")
            self._set_status(f"Configuration saved to {CONF_FILE}.", "ok")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _try_load_config(self):
        try:
            with open(CONF_FILE, "r") as f:
                data = json.load(f)
            tip_raw = data.get("tip", TIP_MIN)
            idx = tip_raw - TIP_MIN
            if 0 <= idx < len(DEVICE_NAMES):
                self._tip_combo.current(idx)
            self.d_int_var.set(str(data.get("d_int", "")))
            self.d_orif_var.set(str(data.get("d_orif", "")))
            self._update_beta()
        except Exception:
            pass

    def _try_load_composition(self):
        try:
            with open(COMP_FILE, "r") as f:
                data = json.load(f)
            fracs = data.get("fractions", [])
            if len(fracs) == NUM_COMPONENTS:
                for i in range(NUM_COMPONENTS):
                    self.comp_vars[i + 1].set(f"{float(fracs[i]):.8f}")
                self._update_sum()
        except Exception:
            pass

    # ── Reference conditions ───────────────────────────────────────────────────

    def _build_ref(self) -> CountryRef:
        sel = self.ref_sel.get()
        name, n, temps, labels = REF_OPTIONS[sel - 1]
        temps = list(temps)
        if sel == 5:
            try:
                temps[0] = float(self.custom_t.get())
            except ValueError:
                temps[0] = 20.0
        return CountryRef(name, n, temps, list(labels))

    # ── Calculation ────────────────────────────────────────────────────────────

    def _calculate(self):
        self._status_lbl.config(text="")

        if self.bwr is None:
            msg = "Apply the composition first (Composition tab → 'Apply composition' button)."
            self._status_lbl.config(text=msg)
            self._set_status(msg, "error")
            return

        try:
            temperature   = float(self.temp_var.get())
            pressure      = float(self.press_var.get())
            pressure_diff = float(self.dp_var.get())
        except ValueError:
            self._status_lbl.config(text="Invalid measurement conditions.")
            self._set_status("Invalid measurement conditions.", "error")
            return

        if temperature <= -273.15:
            self._status_lbl.config(text="Temperature below absolute zero (-273.15°C).")
            self._set_status("Temperature below absolute zero.", "error")
            return
        if pressure <= 0:
            self._status_lbl.config(text="Pressure must be positive.")
            self._set_status("Pressure must be positive.", "error")
            return
        if pressure_diff <= 0:
            self._status_lbl.config(text="Differential pressure must be positive.")
            self._set_status("Differential pressure must be positive.", "error")
            return
        if pressure_diff >= pressure:
            msg = (f"Differential pressure ({pressure_diff} kPa) must be "
                   f"less than pressure ({pressure} kPa).")
            self._status_lbl.config(text=msg)
            self._set_status(msg, "error")
            return

        try:
            d_int  = float(self.d_int_var.get())
            d_orif = float(self.d_orif_var.get())
        except ValueError:
            self._status_lbl.config(text="Invalid diameters.")
            self._set_status("Invalid diameters.", "error")
            return

        if d_int <= 0 or d_orif <= 0:
            self._status_lbl.config(text="Diameters must be positive.")
            self._set_status("Diameters must be positive.", "error")
            return
        if d_orif >= d_int:
            msg = (f"Orifice diameter ({d_orif} mm) must be less than "
                   f"pipe diameter ({d_int} mm).")
            self._status_lbl.config(text=msg)
            self._set_status(msg, "error")
            return

        # Use thermally-corrected diameters — same formula as calc_mass_flow() —
        # so this pre-check and the ISO 5167 internal check are always consistent.
        d_int_t  = d_int  * (1.0 + THERMAL_EXP_PIPE    * (temperature - REF_TEMP_CELSIUS))
        d_orif_t = d_orif * (1.0 + THERMAL_EXP_ORIFICE * (temperature - REF_TEMP_CELSIUS))
        beta = d_orif_t / d_int_t
        if beta < 0.10 or beta > 0.80:
            msg = f"β(t) = {beta:.4f} outside ISO 5167 range [0.10, 0.80]."
            self._status_lbl.config(text=msg)
            self._set_status(msg, "error")
            return

        tip_raw = self._tip_combo.current() + TIP_MIN
        tip     = DeviceType(tip_raw)
        ref     = self._build_ref()

        self.config(cursor="watch")
        self._set_status("Calculating…", "normal")
        self.update_idletasks()
        try:
            ror_ref = [0.0, 0.0]
            for i in range(ref.m_n):
                ror_ref[i], _ = calc_density(ref.m_t[i], 1.0, self.bwr)

            ro, iter_rho = calc_density(temperature, pressure / KPA_PER_ATM, self.bwr)
            if ro <= 0.0:
                msg = (f"BWRS: density did not converge "
                       f"(T={temperature:.1f}°C, P={pressure:.1f} kPa).")
                self._status_lbl.config(text=msg)
                self._set_status(msg, "error")
                return

            eta = calc_viscosity(temperature, ro, self.x,
                                 self.thermo.m_rocCrit, self.thermo.m_csi)

            qm, flow, iter_qm, iso_err = calc_mass_flow(
                pressure_diff, pressure, temperature,
                tip, d_int, d_orif, ro, eta, self.kappa_mix,
            )
            if qm == 0.0:
                msg = iso_err if iso_err else "Mass flow calculation error (ISO 5167)."
                self._status_lbl.config(text=msg)
                self._set_status(msg, "error")
                return

            result_text = self._format_results(
                tip, d_int, d_orif, temperature, pressure, pressure_diff,
                ro, eta, qm, flow, ref, ror_ref,
            )
            self._show_results(result_text)
            self._set_status(
                f"Calculation complete  ·  Qm = {qm * SECONDS_PER_HOUR:.2f} kg/h  "
                f"·  ρ = {ro:.4f} kg/m³  ·  Re = {flow.m_reynolds:.4g}",
                "ok"
            )
        finally:
            self.config(cursor="")

    # ── Results formatting ─────────────────────────────────────────────────────

    def _format_results(self, tip, d_int, d_orif, temperature, pressure,
                        pressure_diff, ro, eta, qm, flow, ref, ror_ref):
        bwr = self.bwr
        x   = self.x

        def row(label, fmt, val, unit):
            pad = max(0, 44 - len(label))
            s = f"  {label}" + " " * pad + " : " + fmt.format(val)
            if unit:
                s += f"  [{unit}]"
            return s

        H = "  " + "─" * 76
        D = "  " + "═" * 76

        z_tp        = ((pressure / KPA_PER_ATM) * bwr.m_molarMass
                       / (ro * GAS_CONSTANT_R * (temperature + KELVIN_OFFSET)))
        speed_sound = math.sqrt(flow.m_kappa * pressure * 1000.0 / ro)
        mach_number = flow.m_velocity / speed_sound
        kin_visc    = (eta / ro) * 1.0e6
        dp_over_p   = pressure_diff / pressure * 100.0

        dt_ref = temperature - REF_TEMP_CELSIUS
        corr_D = THERMAL_EXP_PIPE    * dt_ref * 100.0
        corr_d = THERMAL_EXP_ORIFICE * dt_ref * 100.0

        lines = [
            D,
            f"  RESULTS  —  {tip_name(tip)}",
            f"  D = {d_int:.2f} mm  ·  d = {d_orif:.2f} mm  ·  β = {flow.m_beta:.4f}",
            f"  D(t) = {flow.m_DWorkingMm:.3f} mm  ·  d(t) = {flow.m_dWorkingMm:.3f} mm"
            f"  ·  t = {temperature:.1f}°C",
        ]
        if abs(corr_D) > 0.10 or abs(corr_d) > 0.10:
            lines.append(
                f"  Note: thermal expansion at {temperature:.0f}°C:"
                f"  ΔD = {corr_D:+.3f}%,  Δd = {corr_d:+.3f}%"
            )
        lines += [
            D, "",
            "  Measurement conditions", H,
            row("Temperature",             "{:10.2f}", temperature,   "°C"),
            row("Absolute pressure",       "{:10.2f}", pressure,      "kPa"),
            row("Differential pressure",   "{:10.2f}", pressure_diff, "kPa"),
            "", "  Fluid  (at t, p)", H,
            row("Density ρ(t,p)",                  "{:10.4f}", ro,                  "kg/m³"),
            row("Dynamic viscosity η(t,p)",         "{:10.4f}", eta * PA_TO_MICRO_PA, "μPa·s"),
            row("Kinematic viscosity η/ρ",          "{:10.4f}", kin_visc,             "mm²/s"),
            row("Compressibility factor Z(t,p)",    "{:10.6f}", z_tp,                 "—"),
            row("Speed of sound c",                 "{:10.2f}", speed_sound,          "m/s"),
            row("Mach number Ma",                   "{:10.5f}", mach_number,          "—"),
            row("Δp / p",                           "{:10.3f}", dp_over_p,            "%"),
            "", "  Flow rates", H,
            row("Mass flow Qm",  "{:10.4f}", qm,                    "kg/s"),
            row("Mass flow Qm",  "{:10.2f}", qm * SECONDS_PER_HOUR, "kg/h"),
        ]
        for i in range(ref.m_n):
            if ror_ref[i] > 0.0:
                qhref = SECONDS_PER_HOUR / ror_ref[i] * qm
                lines.append(
                    row(f"Volumetric {ref.m_t[i]:5.2f}°C / 101.325 kPa",
                        "{:10.2f}", qhref, ref.m_label[i])
                )
        lines += [
            row("Volumetric at (t,p)", "{:10.2f}",
                SECONDS_PER_HOUR / ro * qm, "m³/h"),
            "", "  Hydraulics", H,
            row("Mean velocity v",          "{:10.2f}", flow.m_velocity,     "m/s"),
            row("Pressure loss",            "{:10.2f}", flow.m_pressureLoss, "kPa"),
            row("Throttle ratio β",         "{:10.4f}", flow.m_beta,          "—"),
            row("Reynolds number Re",       "{:10.4g}", flow.m_reynolds,     "—"),
            row("Discharge coefficient C",  "{:10.6f}", flow.m_coefC,        "—"),
            row("Expansibility factor ε",   "{:10.6f}", flow.m_epsilon,      "—"),
            row("Isentropic exponent κ",    "{:10.4f}", flow.m_kappa,        "—"),
        ]

        # Calorific
        hhv_mol   = sum(x[i] * HHV_TABLE[i] for i in range(1, NUM_COMPONENTS + 1))
        lhv_mol   = sum(x[i] * LHV_TABLE[i] for i in range(1, NUM_COMPONENTS + 1))
        m_kg      = bwr.m_molarMass * 1e-3
        hhv_kg    = hhv_mol / m_kg
        lhv_kg    = lhv_mol / m_kg
        # ISO 6976:2016 sec. 5: calorific values use ideal-gas molar volumes, not BWRS density
        hhv_0c    = hhv_mol / MOLAR_VOL_0C
        lhv_0c    = lhv_mol / MOLAR_VOL_0C
        hhv_15c   = hhv_mol / MOLAR_VOL_15C
        lhv_15c   = lhv_mol / MOLAR_VOL_15C
        hhv_20c   = hhv_mol / MOLAR_VOL_20C
        lhv_20c   = lhv_mol / MOLAR_VOL_20C
        rel_d     = bwr.m_molarMass / MOLAR_MASS_AIR
        sqrt_d    = math.sqrt(rel_d)
        wobbe_0c  = hhv_0c  / sqrt_d
        wobbe_15c = hhv_15c / sqrt_d
        wobbe_20c = hhv_20c / sqrt_d
        qe_hhv_kw = qm * hhv_kg * KJ_PER_MJ
        qe_hhv_mj = qe_hhv_kw * MJ_PER_KWH
        qe_lhv_kw = qm * lhv_kg * KJ_PER_MJ
        qe_lhv_mj = qe_lhv_kw * MJ_PER_KWH

        lines += [
            "", "  Calorific  (gross / net · ISO 6976:2016)", H,
            row("HHV mixture (per mass)",                 "{:10.4f}", hhv_kg,    "MJ/kg"),
            row("LHV mixture (per mass)",                 "{:10.4f}", lhv_kg,    "MJ/kg"),
            row("HHV mixture   0°C / 101.325 kPa",        "{:10.4f}", hhv_0c,    "MJ/m³"),
            row("LHV mixture   0°C / 101.325 kPa",        "{:10.4f}", lhv_0c,    "MJ/m³"),
            row("HHV mixture  15°C / 101.325 kPa",        "{:10.4f}", hhv_15c,   "MJ/m³"),
            row("LHV mixture  15°C / 101.325 kPa",        "{:10.4f}", lhv_15c,   "MJ/m³"),
            row("HHV mixture  20°C / 101.325 kPa",        "{:10.4f}", hhv_20c,   "MJ/m³"),
            row("LHV mixture  20°C / 101.325 kPa",        "{:10.4f}", lhv_20c,   "MJ/m³"),
            row("Relative density d",                     "{:10.6f}", rel_d,     "—"),
            row("Wobbe index Ws   0°C  (HHV)",            "{:10.4f}", wobbe_0c,  "MJ/m³"),
            row("Wobbe index Ws  15°C  (HHV)",            "{:10.4f}", wobbe_15c, "MJ/m³"),
            row("Wobbe index Ws  20°C  (HHV)",            "{:10.4f}", wobbe_20c, "MJ/m³"),
            row("Energy flow Qe  (HHV)",                  "{:10.4f}", qe_hhv_kw, "kW"),
            row("Energy flow Qe  (HHV)",                  "{:10.2f}", qe_hhv_mj, "MJ/h"),
            row("Energy flow Qe  (LHV)",                  "{:10.4f}", qe_lhv_kw, "kW"),
            row("Energy flow Qe  (LHV)",                  "{:10.2f}", qe_lhv_mj, "MJ/h"),
            "", D,
        ]
        return "\n".join(lines)

    # pattern: "  label...  :  value  [unit]"
    _ROW_RE = re.compile(r'^(  .+?)( : )( *-?[\d.]+(?:[eE][+-]?\d+)?)(.*)$')

    def _show_results(self, text: str):
        w = self._results_txt
        w.config(state=tk.NORMAL)
        w.delete("1.0", tk.END)

        for line in text.splitlines():
            if "═" in line:
                w.insert(tk.END, line + "\n", "sep_d")
            elif "─" in line:
                w.insert(tk.END, line + "\n", "sep_s")
            elif line.strip().startswith("RESULTS"):
                w.insert(tk.END, line + "\n", "title")
            elif line.strip().startswith("Note:"):
                w.insert(tk.END, line + "\n", "note")
            elif (line.startswith("  D =") or line.startswith("  D(t)")):
                w.insert(tk.END, line + "\n", "info")
            elif line and not line.strip().startswith(" :") and " : " not in line:
                stripped = line.strip()
                if stripped and not stripped[0].isdigit():
                    w.insert(tk.END, line + "\n", "section")
                else:
                    w.insert(tk.END, line + "\n", "info")
            else:
                m = self._ROW_RE.match(line)
                if m:
                    label, colon, value, rest = m.groups()
                    unit_m = re.match(r'^(\s+\[)([^\]]+)(\].*)$', rest)
                    w.insert(tk.END, label,  "label")
                    w.insert(tk.END, colon,  "label")
                    w.insert(tk.END, value,  "value")
                    if unit_m:
                        w.insert(tk.END, unit_m.group(1), "unit")
                        w.insert(tk.END, unit_m.group(2), "unit")
                        w.insert(tk.END, unit_m.group(3), "unit")
                    else:
                        w.insert(tk.END, rest, "unit")
                    w.insert(tk.END, "\n")
                else:
                    w.insert(tk.END, line + "\n", "info")

        w.config(state=tk.DISABLED)
        self.nb.select(3)

    # ── Clipboard / Save ───────────────────────────────────────────────────────

    def _copy_results(self):
        content = self._results_txt.get("1.0", tk.END)
        self.clipboard_clear()
        self.clipboard_append(content)
        messagebox.showinfo("OK", "Results copied to clipboard.")

    def _save_results(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="bwrs_results.txt",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._results_txt.get("1.0", tk.END))
                messagebox.showinfo("OK", f"Saved to {path}")
                self._set_status(f"Results saved to {path}.", "ok")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ── Help ───────────────────────────────────────────────────────────────────

    _HELP_TEXT = """\
BWRS GAS FLOW CALCULATOR  —  Help
══════════════════════════════════════════════════════════════════════════════

WHAT THIS APPLICATION CALCULATES
─────────────────────────────────
This calculator determines the mass flow rate of a gas mixture through a
differential-pressure flow device (orifice plate, nozzle, or Venturi tube).
Starting from the measured pressure drop across the device it also derives:

  • Volumetric flow at one or two reference conditions (Nm³/h, Sm³/h, m³/h)
  • Volumetric flow at line conditions
  • Gas density, dynamic and kinematic viscosity
  • Compressibility factor Z, speed of sound, Mach number
  • Permanent pressure loss through the device
  • Higher and lower calorific values (HHV / LHV) per unit mass and volume
  • Wobbe index at 0 °C, 15 °C and 20 °C
  • Energy flow (kW and MJ/h) based on HHV and LHV

NOTE: Measurement uncertainty propagation (ISO 5167-1, six sources: C, ε,
  d, D, Δp, ρ) is implemented in the console UI only and is not yet
  available in this graphical interface.


CALCULATION MODELS
──────────────────
Benedict-Webb-Rubin-Starling (BWRS) equation of state
  Used to calculate gas-phase density from temperature and pressure.
  11-parameter form with Starling (1973) mixing rules:
    – Quadratic mixing rules (N²) for A₀, B₀, C₀, D₀, E₀, γ
    – Cubic mixing rules (N³) for a, b, c, d, α
  Reference: Starling, K.E., "Fluid Thermodynamic Properties for Light
             Petroleum Systems", Gulf Publishing, Houston (1973).

Chapman-Enskog viscosity model with high-density correction
  Dilute-gas mixture viscosity via Chapman-Enskog kinetic theory.
  High-density correction by Chung, Lee & Starling / Nishiumi & Saito.
  Reference: Nishiumi, H. & Saito, S., J. Chem. Eng. Japan 8(5), 356–360 (1975).

ISO 5167 discharge coefficient (Reader-Harris / Gallagher)
  The mass flow rate is obtained by iterating on the Reynolds number until
  convergence. The discharge coefficient C and expansibility factor ε are
  recalculated at each iteration.
  Reference: ISO 5167-2/3/4:2003.

Isentropic exponent κ
  Calculated from the ideal-gas heat capacity Cp° of the mixture at 20 °C:
    κ = Cp° / (Cp° − R)

ISO 6976:2016 calorific values
  Molar HHV and LHV for each component; mixed by molar fractions.
  Converted to MJ/kg and MJ/m³ at standard reference volumes.


SUPPORTED FLOW DEVICES  (ISO 5167)
────────────────────────────────────
  1  Orifice plate — corner taps           β : 0.23 – 0.80
  2  Orifice plate — flange taps           β : 0.20 – 0.75
  3  Orifice plate — D and D/2 taps        β : 0.20 – 0.75
  4  ISA 1932 nozzle                       β : 0.30 – 0.80
  5  Long-radius nozzle (ASME)             β : 0.20 – 0.80
  6  Classical Venturi — rough-cast        β : 0.30 – 0.75,  C ≈ 0.984
  7  Classical Venturi — machined          β : 0.40 – 0.75,  C ≈ 0.995
  8  Classical Venturi — welded sheet      β : 0.40 – 0.70,  C ≈ 0.985
  9  Venturi nozzle                        β : 0.316 – 0.775

Each device type enforces its own pipe-diameter (D), orifice-diameter (d),
throttle-ratio (β = d/D), and Reynolds-number validity ranges from ISO 5167.


GAS COMPONENTS  (35 total)
───────────────────────────
Hydrocarbons: CH₄, C₂H₆, C₃H₈, i-C₄, n-C₄, neopentane, i-C₅, n-C₅,
  2,2-dimethylbutane, 2,3-dimethylbutane, 3-methylpentane, 2-methylpentane,
  n-C₆, 2,4-dimethylpentane, 2,2,3-trimethylbutane, 2-methylhexane,
  3-methylhexane, 3-ethylpentane, n-C₇, 2,2,4-trimethylpentane (isooctane),
  n-C₈, benzene, toluene
Other: H₂, CO, H₂S, He, Ar, N₂, O₂, CO₂, C₂H₄, C₃H₆, NH₃, C₂H₂


REFERENCE CONDITIONS FOR VOLUMETRIC FLOW
──────────────────────────────────────────
  Romania / EU  DIN 1343  :   0 °C and 15 °C,  101.325 kPa  →  Nm³/h, Sm³/h
  ISO 13443 / UK / Italy  :  15 °C,             101.325 kPa  →  Sm³/h
  USA  AGA-3  (60 °F)     :  15.56 °C,          101.325 kPa  →  Sm³/h
  Russia  GOST 30319-1    :  20 °C,             101.325 kPa  →  m³/h
  Custom                  :  user-entered °C,   101.325 kPa  →  m³/h


THERMAL EXPANSION CORRECTION
──────────────────────────────
Diameters D and d entered at 20 °C are corrected to the measurement
temperature using material-specific expansion coefficients:
  Pipe   (carbon steel)       α = 12.2 × 10⁻⁶ /°C
  Orifice (stainless steel)   α = 16.5 × 10⁻⁶ /°C


WORKFLOW
─────────────────────────────
  1.  Composition tab  — enter the 35 molar fractions; sum must equal 1.000.
                         Click "Apply composition" to compute BWRS constants.
  2.  Device tab       — select the throttling device type; enter D and d.
                         Choose the reference condition standard.
  3.  Conditions tab   — enter temperature [°C], absolute pressure [kPa],
                         and differential pressure [kPa]; click CALCULATE.
  4.  Results tab      — view the full calculation report; copy or save it.
  5.  Tests tab        — run the built-in validation suite to verify the
                         implementation against NIST WebBook and ISO 5167.


STANDARDS AND REFERENCES
──────────────────────────
  ISO 5167-1:2003   Measurement of fluid flow — General principles
  ISO 5167-2:2003   Orifice plates
  ISO 5167-3:2003   Nozzles and Venturi nozzles
  ISO 5167-4:2003   Classical Venturi tubes
  ISO 6976:2016     Natural gas — Calculation of calorific values, density,
                    relative density and Wobbe indices
  ISO 13443:1996    Natural gas — Standard reference conditions
  DIN 1343:1990     Reference conditions for gases
  AGA Report No. 3  Orifice metering of natural gas (USA, 60 °F reference)
  GOST 30319-1      Flow measurement of natural gas (Russia, 20 °C reference)
  Starling 1973     BWRS equation of state constants for 35 components
  Nishiumi 1975     High-density viscosity correction


VERSION
───────
  v3.0 / 2026  ·  Author: Constantin Agavriloaie  ·  ELCOST Impex  ·  CJ-RO
  © 2004–2026 ELCOST Impex
══════════════════════════════════════════════════════════════════════════════
"""

    def _show_help(self):
        P = PALETTE
        win = tk.Toplevel(self)
        win.title("Help — BWRS Gas Flow Calculator")
        win.geometry("780x620")
        win.minsize(600, 400)
        win.configure(bg=P["bg"])
        win.transient(self)

        # Header strip
        hdr = tk.Frame(win, bg=P["header_bg"], height=40)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Help — BWRS Gas Flow Calculator",
                 bg=P["header_bg"], fg=P["header_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(side=tk.LEFT, padx=16, fill=tk.Y)
        tk.Frame(win, bg=P["accent_bar"], height=2).pack(fill=tk.X, side=tk.TOP)

        # Scrolled text area
        txt = scrolledtext.ScrolledText(
            win, wrap=tk.WORD,
            font=("Courier New", 10),
            bg=P["dark_bg"], fg=P["dark_fg"],
            relief="flat", borderwidth=0,
            padx=16, pady=12,
            state=tk.NORMAL,
        )
        txt.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Coloured tags
        txt.tag_config("h1",   foreground="#e5c07b", font=("Courier New", 11, "bold"))
        txt.tag_config("h2",   foreground="#61afef", font=("Courier New", 10, "bold"))
        txt.tag_config("sep",  foreground="#3e4451")
        txt.tag_config("body", foreground="#abb2bf")
        txt.tag_config("kw",   foreground="#98c379")

        for line in self._HELP_TEXT.splitlines(keepends=True):
            stripped = line.rstrip()
            if stripped.startswith("BWRS GAS FLOW"):
                txt.insert(tk.END, line, "h1")
            elif stripped.startswith("══") or stripped.startswith("──"):
                txt.insert(tk.END, line, "sep")
            elif stripped and stripped == stripped.upper() and len(stripped) > 4 and stripped[0].isalpha():
                txt.insert(tk.END, line, "h2")
            elif stripped.startswith("  ") and " : " not in stripped and stripped.lstrip().startswith(tuple("123456789")):
                txt.insert(tk.END, line, "kw")
            else:
                txt.insert(tk.END, line, "body")

        txt.config(state=tk.DISABLED)

        # Close button
        btn_bar = tk.Frame(win, bg=P["bg"])
        btn_bar.pack(fill=tk.X, pady=8)
        ttk.Button(btn_bar, text="Close", command=win.destroy).pack(side=tk.RIGHT, padx=12)


def run():
    app = BwrsApp()
    app.mainloop()


if __name__ == "__main__":
    run()

"""Process facts per PDK — the single source every block, testbench and specs.py reads.

Selected by $PDK (the nix shell exports it, e.g. sky130A). Switching $PDK and re-running
is the whole port. Only *process* facts live here; design choices (caps, sizing, delay
chains) belong to specs.py or the owning block's netlist script.

A PDK entry has two kinds of field:
  declared   read from the PDK's own files (model lib, DRC decks, model params) — each
             value cites where it came from
  measured   characterised by pdk_char.py with the PDK's own models and cached in
             pdk_char/<name>.json; a declared value always wins over a measured one

Adding a PDK = subclass PDKConfig with the declared fields, register it, run
`python3 analog/docs/pdk_char.py <name>` once, then `python3 analog/common/hotswap.py`.

How a PDK is simulated is declared, not coded: `model_library(corner)` writes a wrapper
under pdk_models/<name>/ with the PDK's params, the corner's lib section and any
always-on sections, and returns a SpiceRack ModelLibrary that includes it. The corner
token `<corner><mismatch_suffix>` (e.g. tt_mm, typical_mm) turns on local mismatch.

Projection PDKs (asap7_proj, tsmc_n4_proj) have no SPICE models; they carry `t_q_grid`,
`cal_proj`, `topology_flags` for the architecture-projection math in scripts/compiler/metrics.

Self-check: python3 analog/docs/pdk_specs.py  -> prints every field per PDK.
"""
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEASURED = ("vth_n", "vth_p", "un_cox", "up_cox", "ss_mv_dec", "a_vt", "mim_ff_um2", "mim_ff_um",
            "res_poly_ohm_sq", "res_poly_lotc_ohm_sq", "t_inv_ps_per_ff")


def pdk_root() -> Path:
    env = os.environ.get("PDK_ROOT")
    for p in ([Path(env)] if env else []) + [Path.home() / ".volare", Path.home() / ".ciel"]:
        if p.is_dir():
            return p
    raise FileNotFoundError("PDK_ROOT not set and no ~/.volare or ~/.ciel — run ./env.sh")


@dataclass
class PDKConfig:
    name: str
    vdd: float
    min_l: float                 # um, drawn
    nfet: str
    pfet: str
    min_w: float = 0.0           # um, drawn
    nfet_lvt: str = ""
    pfet_lvt: str = ""
    pfet_hvt: str = ""
    # -- how devices are written (python format strings; W/L already unit-formatted)
    geom_suffix: str = "u"       # appended to W/L in um; "" when the lib sets scale=1u
    fet_card: str = "X{name} {d} {g} {s} {b} {model} W={w} L={l}{extra}"
    mult_card: str = " m={m}"    # instance multiplicity; must scale current AND mismatch
    w_max: float = 0.0           # um, widest single instance the models bin (0 = none)
    mim_cap: str = ""            # 2-terminal MIM cap device
    mim_card: str = "X{name} {p} {n} {model} W={w} L={l}"
    res_poly: str = ""           # dense (high sheet R) 3-terminal poly resistor
    res_poly_w: float = 0.0      # um, width it is drawn at
    res_poly_lotc: str = ""      # low-tempco poly resistor for references
    res_poly_lotc_w: float = 0.0
    res_card: str = "X{name} {p} {n} {b} {model} W={w} L={l}"
    # -- how models are loaded
    variant: str = ""            # directory under $PDK_ROOT
    lib_rel: str = ""            # ngspice lib, relative to <variant>/libs.tech/ngspice
    setup_rel: tuple = ()        # files to .include before the lib
    params: dict = field(default_factory=dict)       # .param set before the lib
    extra_sections: tuple = ()   # lib sections always loaded after the corner; "{p}" is
    passive_corner: dict = field(default_factory=dict)  # replaced by passive_corner[corner]
    corners: tuple = ()          # corner sections, verbatim
    typical: str = ""
    mismatch_suffix: str = "_mm"  # corner token suffix that enables local mismatch
    mm_native: bool = False      # True: the lib has a <corner><suffix> section itself
    mm_params: dict = field(default_factory=dict)    # else: params that enable it
    mc_section: str = ""         # process+mismatch section, if the PDK has one
    gmid_device_file: str = ""   # per-device model file for GmIDVisualizer ("" = wrapper)
    # -- layout / wiring (declared from DRC decks and model files)
    r_sq_wire: float = 0.0       # signal-metal sheet R (ohm/sq)
    wire_pitch: float = 0.0      # signal-metal pitch (um)
    # -- measured by pdk_char.py unless declared
    un_cox: float = 0.0          # uA/V^2
    up_cox: float = 0.0
    vth_n: float = 0.0           # V
    vth_p: float = 0.0           # V, |Vth|
    ss_mv_dec: float = 0.0       # subthreshold swing (mV/dec)
    a_vt: float = 0.0            # Pelgrom VT coefficient, sigma(dVth) of a pair (mV*um)
    mim_ff_um2: float = 0.0      # MIM area coefficient, fF/um^2  } C = ca*s^2 + 4*cp*s
    mim_ff_um: float = 0.0       # MIM perimeter coefficient, fF/um } (square, side s um)
    mim_min_side: float = 0.0    # um, smallest drawable square MIM (DRC)
    res_poly_ohm_sq: float = 0.0
    res_poly_lotc_ohm_sq: float = 0.0
    # poly-resistor local mismatch, sigma(dR/R) * sqrt(W*L) in um. Declared from the model
    # files: neither PDK varies resistor mismatch in ngspice Monte Carlo, so a tt_mm run
    # reads 0 — size resistor matching against these instead. 0.0 = not stated by the PDK.
    res_poly_a_r: float = 0.0
    res_poly_lotc_a_r: float = 0.0
    t_inv_ps_per_ff: float = 0.0  # min-inverter delay slope (ps/fF)
    # -- design target AnalogIOC carried per PDK (specs.py reads it)
    jitter_budget_s: float = 0.0  # PWM edge jitter budget (s)
    # -- projection-only
    t_q_grid: float = 0.0
    cal_proj: dict = field(default_factory=dict)
    topology_flags: dict = field(default_factory=dict)

    @property
    def cap_density_mim(self) -> float:
        """AnalogIOC's name, kept for specs.py / scripts/compiler/metrics."""
        return self.mim_ff_um2

    @property
    def installed(self) -> bool:
        return bool(self.lib_rel)

    def sections(self) -> tuple:
        return (self.corners + tuple(c + self.mismatch_suffix for c in self.corners)
                + ((self.mc_section,) if self.mc_section else ()))

    def ngspice_dir(self) -> Path:
        return pdk_root() / self.variant / "libs.tech" / "ngspice"

    def lib_path(self) -> Path:
        if not self.installed:
            raise RuntimeError(f"{self.name} is a projection — it has no SPICE models")
        return self.ngspice_dir() / self.lib_rel

    def model_lines(self, corner: str = "") -> list:
        """Deck lines that load this PDK at `corner` (a corner, corner+mismatch_suffix,
        or the mc section)."""
        corner = corner or self.typical
        if corner not in self.sections():
            raise ValueError(f"{self.name}: no corner {corner!r}; have {self.sections()}")
        sfx = self.mismatch_suffix
        mm = corner.endswith(sfx) and corner[:-len(sfx)] in self.corners
        base = corner[:-len(sfx)] if mm else corner
        params = dict(self.params, **(self.mm_params if mm and not self.mm_native else {}))
        lines = [f'.include "{self.ngspice_dir() / s}"' for s in self.setup_rel]
        lines += [f".param {k}={v}" for k, v in params.items()]
        lines.append(f'.lib "{self.lib_path()}" {corner if mm and self.mm_native else base}')
        pc = self.passive_corner.get(base, base)
        lines += [f'.lib "{self.lib_path()}" {s.format(p=pc)}' for s in self.extra_sections]
        return lines

    def model_file(self, corner: str = "") -> Path:
        """A wrapper file holding model_lines(corner), rewritten only when it changes."""
        corner = corner or self.typical
        path = HERE / "pdk_models" / self.name / f"{corner}.spice"
        text = f"* {self.name} {corner} — generated by pdk_specs.py\n" + \
            "\n".join(self.model_lines(corner)) + "\n"
        if not path.exists() or path.read_text() != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return path

    def model_library(self, corner: str = ""):
        """spicerack.ModelLibrary loading this PDK at `corner` (see model_lines)."""
        import spicerack as ps
        return ps.ModelLibrary(str(self.model_file(corner)))

    def lib_line(self, corner: str = "") -> str:
        """One `.include` of the wrapper, for decks that bypass SpiceRack."""
        return f'.include "{self.model_file(corner)}"'

    def um(self, x: float) -> str:
        """A W/L in um, formatted for this PDK's netlist convention."""
        return f"{x:g}{self.geom_suffix}"

    def missing(self) -> list:
        """Fields code relies on that are still unset (0 / "")."""
        need = ("min_w", "mim_cap", "res_poly", "res_poly_lotc", "r_sq_wire",
                "wire_pitch") + MEASURED
        return [f for f in need if not getattr(self, f)] if self.installed else []


class Sky130(PDKConfig):
    def __init__(self, variant: str = "sky130A"):
        super().__init__(
            name="sky130", variant=variant, lib_rel="sky130.lib.spice",
            vdd=1.8, min_l=0.15, min_w=0.42,
            nfet="sky130_fd_pr__nfet_01v8", pfet="sky130_fd_pr__pfet_01v8",
            nfet_lvt="sky130_fd_pr__nfet_01v8_lvt", pfet_lvt="sky130_fd_pr__pfet_01v8_lvt",
            pfet_hvt="sky130_fd_pr__pfet_01v8_hvt",
            geom_suffix="",        # all.spice sets .option scale=1.0u
            # the subckt's current ignores `mult`; its mismatch terms use sqrt(l*w*mult)
            mult_card=" m={m} mult={m}",
            w_max=100.0,           # nfet/pfet_01v8 pm3 bins: wmax = 1e-4
            mim_cap="sky130_fd_pr__cap_mim_m3_1",
            mim_min_side=1.0,      # klayout sky130A_mr.drc capm.1: min capm width 1.0 um
            res_poly="sky130_fd_pr__res_xhigh_po_0p35", res_poly_w=0.35,
            res_poly_lotc="sky130_fd_pr__res_high_po_0p35", res_poly_lotc_w=0.35,
            res_card="X{name} {p} {n} {b} {model} L={l}",   # width fixed by the device
            corners=("tt", "ss", "ff", "sf", "fs"), typical="tt",
            mm_native=True, mc_section="mc",
            # the lib's scale=1u breaks GmIDVisualizer's W=10u: use per-device files
            gmid_device_file="libs.ref/sky130_fd_pr/spice/{model}__{corner}.pm3.spice",
            r_sq_wire=0.125,       # met1 sheet R, sky130 PDK docs (AnalogIOC)
            wire_pitch=0.34,       # met1 pitch, sky130 DRC (AnalogIOC)
            # AnalogIOC-sourced electrical values (kept: specs.py is anchored to them)
            un_cox=270.0, up_cox=90.0, vth_n=0.36, vth_p=0.36,
            # a_vt: measured by pdk_char.py (AnalogIOC's ~5 mV*um "130nm class" estimate
            # under-predicted the strongarm Monte Carlo offset by ~1.7x)
            ss_mv_dec=90.0,        # TT/27C (n ~ 1.5)
            t_inv_ps_per_ff=9.2,   # measured: tb_async_ctrl 10.15 ns / 550f per 2-inv stage
            # measured ngspice tt/27C 2026-09-28: L=10 um xhigh_po_0p35 57.7 kohm
            # (tc1 -1.47e-3), high_po_0p35 11.7 kohm (tc1 +0.51e-3). MIM area/perimeter
            # coefficients: measured by pdk_char.py (2 sizes).
            res_poly_ohm_sq=2020.0, res_poly_lotc_ohm_sq=408.0,
            # body_pelgrom in sky130_fd_pr__res_xhigh_po__base / __res_high_po .model.spice
            # (the ngspice slope that would apply it is fixed at 0 in model__linear)
            res_poly_a_r=0.0347, res_poly_lotc_a_r=0.03552,
            jitter_budget_s=200e-12,
        )


class GF180MCU(PDKConfig):
    """3V3 devices. Declared values cite libs.tech/{ngspice,klayout/drc} of gf180mcuD."""
    def __init__(self):
        super().__init__(
            name="gf180mcu", variant="gf180mcuD", lib_rel="sm141064.ngspice",
            vdd=3.3,
            min_l=0.28,            # 3V3 device min L (sm141064 fets_mm default l=2.8e-7)
            min_w=0.22,            # klayout comp.drc DF.2a_LV: min channel width 0.22 um
            nfet="nfet_03v3", pfet="pfet_03v3",
            # every corner section loads fets_mm, which wraps each FET in a subckt -> X
            # cards; its mismatch term is delvto=mis_vth*sw_stat_mismatch (0 = typical).
            # MIM caps and resistors come from their own per-corner sections.
            setup_rel=("design.ngspice",),
            params={"sw_stat_global": 0, "sw_stat_mismatch": 0},
            extra_sections=("mimcap_{p}", "res_{p}"),
            passive_corner={"sf": "typical", "fs": "typical"},
            mm_params={"sw_stat_mismatch": 1},
            corners=("typical", "ss", "ff", "sf", "fs"), typical="typical",
            fet_card="X{name} {d} {g} {s} {b} {model} w={w} l={l}{extra}",
            # fets_mm: current scales with m, mismatch area with par
            mult_card=" m={m} par={m}",
            w_max=100.0,           # sm141064 nfet/pfet_03v3 bins: wmax = 1.00001e-4
            mim_cap="cap_mim_2f0_m3m4_noshield",
            mim_min_side=5.0,      # mim_a.drc MIM.8a: min MIM area 25 um^2
            mim_card="X{name} {p} {n} {model} c_width={w} c_length={l}",
            res_poly="ppolyf_u_1k", res_poly_w=1.0,
            res_poly_lotc="ppolyf_u", res_poly_lotc_w=1.0,
            res_card="X{name} {p} {n} {b} {model} r_width={w} r_length={l}",
            r_sq_wire=0.09,        # sm141064.ngspice typical: rsh_rm1=0.09
            wire_pitch=0.46,       # metal1.drc M1.1 width 0.23 + M1.2a space 0.23
            a_vt=7.148,            # sm141064 fets_mm nfet_03v3 par_vth=0.007148 (V*um)
            jitter_budget_s=200e-12,  # AnalogIOC's sky130 PWM edge target, same node class
        )


class IHP_SG13G2(PDKConfig):
    """1.2 V LV CMOS. Not installed under ~/.volare on this machine: the declaration is
    partial (device cards, passives, layout rules) until it is."""
    def __init__(self):
        super().__init__(
            name="ihp-sg13g2", variant="ihp-sg13g2", lib_rel="sg13g2.lib.spice",
            vdd=1.2, min_l=0.13,
            nfet="sg13_lv_nmos", pfet="sg13_lv_pmos",
            nfet_lvt="sg13_lv_nmos", pfet_hvt="sg13_lv_pmos",
            corners=("typ", "slow", "fast"), typical="typ",
        )


class Asap7Proj(PDKConfig):
    """ASAP7 PROJECTION-GRADE parameters (no SPICE). Confidence tags from AnalogIOC."""
    def __init__(self):
        c_par_vg = 100e-15   # sky130 700f scaled by bank/wire cap shrink (LOW)
        super().__init__(
            name="asap7_proj", vdd=0.70, min_l=0.021,
            nfet="asap7_nfet_rvt", pfet="asap7_pfet_rvt",
            r_sq_wire=2.5,          # M6-class, scaled 7nm BEOL (MEDIUM)
            wire_pitch=0.064,
            a_vt=1.3, ss_mv_dec=63.0, mim_ff_um2=2.0,
            t_inv_ps_per_ff=1.0, jitter_budget_s=50e-12,
            t_q_grid=100e-12,       # snap above ~85 ps row-RC floor (MEDIUM)
            topology_flags={"ota": "two_stage_or_ringamp_0V7",
                            "sizing": "fin_quantized_27nm_pitch"},
            cal_proj={
                "k_cal": 0.99,                              # sky130 measured 0.9906 (MEDIUM)
                "beta_int": 50e-15 / (50e-15 + c_par_vg),   # c_int/(c_int+c_par) (MEDIUM)
                "c_ota_self": 25e-15,                       # 311f f_T-scaled (LOW)
                "i_side_ref": 10e-6,
                "c_par_vg": c_par_vg,
            },
        )


class TsmcN4Proj(PDKConfig):
    """TSMC N4-class PROJECTION-GRADE parameters (no SPICE)."""
    def __init__(self):
        c_par_vg = 80e-15    # sky130 700f scaled by cap shrink (LOW)
        super().__init__(
            name="tsmc_n4_proj", vdd=0.75, min_l=0.018,
            nfet="n4_nfet_svt", pfet="n4_pfet_svt",
            r_sq_wire=3.0, wire_pitch=0.048,
            a_vt=1.0,               # 5nm-class FinFET Pelgrom (LOW)
            ss_mv_dec=65.0,
            mim_ff_um2=3.5,         # stacked MOM, N5-class (MEDIUM)
            t_inv_ps_per_ff=0.8, jitter_budget_s=50e-12,
            t_q_grid=100e-12,       # snap above ~75 ps row-RC floor (MEDIUM)
            topology_flags={"ota": "two_stage_or_ringamp_0V75", "sizing": "fin_quantized"},
            cal_proj={
                "k_cal": 0.99,
                "beta_int": 40e-15 / (40e-15 + c_par_vg),
                "c_ota_self": 20e-15,
                "i_side_ref": 10e-6,
                "c_par_vg": c_par_vg,
            },
        )


_REGISTRY = {"sky130": Sky130, "gf180mcu": GF180MCU, "ihp-sg13g2": IHP_SG13G2,
             "asap7_proj": Asap7Proj, "tsmc_n4_proj": TsmcN4Proj}
# $PDK is the volare variant name; map it to a registry key.
_VARIANT = {"sky130A": "sky130", "sky130B": "sky130", "gf180mcuD": "gf180mcu",
            "ihp-sg13g2": "ihp-sg13g2"}
_cache = {}


def _load_measured(p: PDKConfig):
    path = HERE / "pdk_char" / f"{p.name}.json"
    if path.exists():
        for k, v in json.loads(path.read_text()).get("values", {}).items():
            if k in MEASURED and not getattr(p, k):
                setattr(p, k, v)


def get_pdk(name: str = "") -> PDKConfig:
    """The active PDK ($PDK, default sky130A), or a registry key / variant by name."""
    key = name or os.environ.get("PDK", "sky130A")
    key = _VARIANT.get(key, key)
    if key not in _REGISTRY:
        raise ValueError(f"unknown PDK {key!r}; have {sorted(_REGISTRY)}")
    if key not in _cache:
        p = _REGISTRY[key]()
        v = os.environ.get("PDK", "")
        if key == "sky130" and v.startswith("sky130"):
            p.variant = v
        _load_measured(p)
        _cache[key] = p
    return _cache[key]


if __name__ == "__main__":
    active = get_pdk()
    print(f"active: {active.name} ($PDK={os.environ.get('PDK', '<unset>')})")
    for key in _REGISTRY:
        p = get_pdk(key)
        ok = p.installed and p.lib_path().exists()
        print(f"\n[{key}] " + (f"lib={p.lib_path()}" if p.installed else "(projection)")
              + ("" if ok or not p.installed else "  ** NOT INSTALLED **"))
        for f in fields(p):
            v = getattr(p, f.name)
            if v not in ("", 0.0, (), {}) and f.name != "name":
                print(f"  {f.name} = {v}")
        if ok and p.missing():
            print(f"  ** unset: {p.missing()} — run: python3 analog/docs/pdk_char.py {key}")

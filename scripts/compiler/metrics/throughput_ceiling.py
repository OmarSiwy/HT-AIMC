"""Session-3 Q: "can we hit 1 GHz f_MVM and beat a systolic array on throughput?"

Pure parameter evaluation through analog/schematics/specs.py — NO SPICE, NO
writes outside this file + THROUGHPUT_CEILING.md.  Same runtime-substitution
discipline as pdk_projections.evaluate (TQ_SIM per-PDK, sar_time scaled by the
tau_absorb ratio) so conv_time is not silently inflated.

Answers, in order:
  Q1  f_MVM = 1/pass symbolically; what t_q does 1 GHz need; honest ceiling.
  Q2  f_MVM is NOT a systolic clock — apples-to-apples TOPS and batch-1 latency.
  Q3  raise N, not f.  Where does the N win actually stop, and why.
  Q4  ranked levers (b_x, M, pipelining, more ADCs).
  Q5  node-scaling framework with the constants left as NAMED parameters.
  Q6  two-regime verdict.

Every printed number carries a label: (measured) SPICE-backed, (derived)
arithmetic on measured/committed values, (projected) model extrapolation,
(ASSUMPTION) a named constant a reader must supply/challenge.

Run: PYTHONPATH=analog/schematics:. python3 scripts/compiler/metrics/throughput_ceiling.py
"""
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "analog", "schematics"))
import specs                                              # noqa: E402
from library.pdks.sky130 import Sky130                    # noqa: E402
from library.pdks.asap7_proj import Asap7Proj             # noqa: E402
from library.pdks.tsmc_n4_proj import TsmcN4Proj          # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "THROUGHPUT_CEILING.md")

# ---------------------------------------------------------------------------
# schedule law (committed this session; re-derived + asserted below)
# ---------------------------------------------------------------------------
T_IN_TQ = 136          # merged 128-cycle PWM window + 8 settle-in (derived)
T_SWAP_TQ = 4          # ping-pong swap gap (derived)
PASS_TQ_FLOOR = T_IN_TQ + T_SWAP_TQ                       # 140 t_q

# ---------------------------------------------------------------------------
# systolic reference — NAMED PARAMETERS, fill/replace freely
# ---------------------------------------------------------------------------
SYS = {                       # TPUv1-class, the number in the question
    "name": "TPUv1 MXU (256x256, 28 nm)",
    "rows": 256, "cols": 256, "f_hz": 940e6,
    "node_nm": 28,
    "label": "vendor/published (jouppi2017datacenter)",
}
# Fill these from the other agent's literature pass; the framework below is
# written so ONLY these three constants move.  Left as None => not asserted.
SYS_N4 = {"name": "systolic @ N4 (TPUv5e / Sohu class)",
          "rows": None, "cols": None, "f_hz": None, "node_nm": 4,
          "label": "PLACEHOLDER — fill from the citable-numbers agent"}

# ---------------------------------------------------------------------------
# tile geometry / area anchors (paper sec_eval) — ASSUMPTION-grade
# ---------------------------------------------------------------------------
N_PAPER, M_PAPER = 512, 256       # paper design point (sec_arch)
A_CELL_UM2 = 0.013e6 / (512 * 1024)   # 0.0248 um^2/crosspoint, from the paper's
                                      # 0.013 mm^2 for a physical 512x1024 array
A_CONV_UM2 = 25.0                 # converged converter, um^2/column (paper)
A_CONV_CCO_UM2 = 100.0            # conservative CCO-pitch fallback (paper)
WRAP_MULT = 1.5                   # law:wrapper near-tile digital derating
E_ADC_PJ = 1.55                   # E_ADC(8 b, r=3) per conversion (paper eq:adc)

# ---------------------------------------------------------------------------
# CSNR anchors (committed this session)
# ---------------------------------------------------------------------------
CSNR_MEAS_DB = 28.5      # held-out attention, NOMINAL SPICE (CSNR_HOLDOUT.md)
CSNR_TARGET_DB = 28.0    # attention-class target (specs.SNR_T_ATTN_DB)
CSNR_HYPO_DB = 34.0      # the "what if" point the question asks for
# Pelgrom per-cell unit-cap scatter, sky130 / asap7 / N4 (SERVO_EG.md 1(c)).
# NOT in any SPICE run: tb_csnr.py line 31 — "the tt corner carries no
# mismatch, and the tile's caps are ideal C elements anyway".
PELGROM_CELL = {"sky130": 0.055, "asap7_proj": 0.067, "tsmc_n4_proj": 0.094}

# ---------------------------------------------------------------------------
# node-scaling law — ASSUMPTIONS, stated so they can be rejected wholesale
# ---------------------------------------------------------------------------
FO4_PS = {130: 45.0, 28: 12.5, 7: 6.0, 4: 5.0}   # ASSUMPTION (public class figs)


def sub(pdk, _tq, fn, *a, **kw):
    t_q = _tq
    """Evaluate specs.<fn> with TQ_SIM = t_q and sar_time scaled by the
    tau_absorb ratio vs the sky130 anchor (pdk_projections hook 2).  Without
    the sar scaling conv_time is inflated by ~3x at N4."""
    if getattr(pdk, "cal_proj", None):
        specs._CAL[pdk.name] = pdk.cal_proj
    saved = (specs.TQ_SIM, specs.sar_time)
    try:
        specs.TQ_SIM = 10e-9
        sky = Sky130()
        tau_ref, sar_ref = specs.tau_absorb(sky), specs.sar_time(sky)
        specs.TQ_SIM = t_q
        tau = specs.tau_absorb(pdk)
        specs.sar_time = lambda p=None, s=sar_ref * tau / tau_ref: s
        return fn(pdk, *a, **kw)
    finally:
        specs.TQ_SIM, specs.sar_time = saved


# ===========================================================================
# Q1 — what sets f_MVM
# ===========================================================================
def pass_time(t_q, t_conv, K):
    """f_MVM = 1/pass.  pass(K) = max(136 t_q, T_conv/K) + 4 t_q.
    K=1 (measured-CSNR point): T_conv >> 136 t_q => CONVERSION binds.
    K -> inf:                  pass -> 140 t_q  => PWM WINDOW binds, hard."""
    return max(T_IN_TQ * t_q, t_conv / K) + T_SWAP_TQ * t_q


def tq_for_fmvm(f_hz):
    """K -> inf ceiling inverted: the t_q a target f_MVM demands."""
    return 1.0 / (PASS_TQ_FLOOR * f_hz)


def row_rc_5rc(pdk, m_cols, n_seg=1):
    """specs.t_q_floor's RC term, generalised in the ONE variable it actually
    depends on: the number of COLUMNS on the row wire.  (specs hardwires
    N_COLS=17 for the length and N_ROWS=16 for the cap — an off-by-one the
    generalisation removes; at M=17 this reads 97 ps vs specs' 92 ps.)

    row_len = M * 15 * pitch;  R = r_sq * row_len/pitch;  C = M*15*C_u + 0.2fF/um.
    => R ~ M and C ~ M, so 5RC ~ M^2.  N (rows) does NOT appear: a row wire
    crosses columns, not rows.  n_seg = locally re-driven segments (~1/n_seg^2)."""
    seg_m = m_cols / n_seg
    row_len = seg_m * 15 * pdk.wire_pitch
    r_row = pdk.r_sq_wire * row_len / pdk.wire_pitch
    c_row = seg_m * 15 * specs.c_u(pdk) + row_len * 0.2e-15
    return 5 * r_row * c_row


def row_rc_tq_floor(pdk, m_cols, n_seg=1):
    return max(row_rc_5rc(pdk, m_cols, n_seg), pdk.jitter_budget_s)


# ===========================================================================
# Q2 — like-for-like against a systolic array
# ===========================================================================
def systolic(rows, cols, f_hz):
    """Weight-stationary systolic accounting.  Peak is the marketing number;
    the other two are what a batch-1 decode GEMV actually gets.

    fill/drain: an activation vector is skewed in over `rows` cycles and the
    partial sums drain down `cols` rows => rows+cols+B-1 cycles for B vectors.
    weight load: `rows` cycles per NEW weight tile (weights are not resident
    for a 7B model; every tile is new at batch 1)."""
    macs = rows * cols
    peak_tops = 2 * macs * f_hz / 1e12
    cyc_b1 = rows + cols + 1
    lat_b1 = cyc_b1 / f_hz
    return {
        "macs": macs, "peak_tops": peak_tops,
        "b1_cycles": cyc_b1, "b1_latency_s": lat_b1,
        "b1_util": 1.0 / cyc_b1,
        "b1_tops": 2 * macs / lat_b1 / 1e12,
        "b1_tops_wload": 2 * macs / ((cyc_b1 + rows) / f_hz) / 1e12,
    }


# ===========================================================================
# Q3 — raise N, not f.  Where the N win stops.
# ===========================================================================
# The load-bearing structural fact (weight_tile.py docstring, verbatim):
#   "Column rails are the integrator virtual grounds (OTA inn nodes)."
#   "TG to the column rail during phi2 (transfer)."
# => every one of the N crosspoint banks lands on the OTA virtual ground during
# the phi2 settling event that tau_absorb measures.  C_par_vg is therefore
# LINEAR IN N, and tau_absorb (hence conv_time) is linear in N.  That is the
# feedback that decides whether raising N buys anything.
C_BALL_SKY = 4e-15        # bank-top ballast (weight_tile.C_BALL, measured pick)
N_ANCHOR = specs.N_ROWS   # 16 — the rows the committed _CAL c_par_vg is for


def c_par_row(pdk):
    """Per-row load on the virtual ground: top-plate ballast (cap-shrink
    scaled off sky130) + the bank's own binary array (<=15 C_u)."""
    ball = C_BALL_SKY * specs.c_u(pdk) / specs.c_u(Sky130())
    return ball + 15 * specs.c_u(pdk)


def c_par_vg(pdk, N):
    """c_par0 (C_RAIL + wire, N-independent) + N * per-row bank load.
    c_par0 back-solved so N = N_ANCHOR reproduces the committed _CAL value."""
    c_row = c_par_row(pdk)
    c0 = max(0.0, specs.cal(pdk)["c_par_vg"] - N_ANCHOR * c_row)
    return c0 + N * c_row


def c_int_n(pdk, N, route):
    """Two ways to hold the +-4 sigma column swing inside V_SWING as N grows.
    The dot product concentrates to sqrt(N) (law:bout), so the full scale that
    must fit V_SWING grows as sqrt(N) and ONE of C_int/C_u must move:
      route 'cint': C_int ~ sqrt(N), C_u fixed  -> no matching cost, area+tau cost
      route 'cu'  : C_int fixed, C_u ~ 1/sqrt(N) -> no area cost, PELGROM cost"""
    c0 = specs.c_int(pdk)
    return c0 * math.sqrt(N / N_ANCHOR) if route == "cint" else c0


def tau_absorb_n(pdk, N, route, t_q):
    """specs.tau_absorb re-derived at row count N.

    tau*gm = A + A*C_par/C_int + C_par,  A = C_filt + C_ota_self.
    Identity check: c_ser = C_int*C_par/(C_int+C_par) and beta = C_int/(C_int+
    C_par), so (c_filt+c_self)/beta + c_ser/beta == A*(C_int+C_par)/C_int + C_par.
    Large N (C_par ~ N, C_int ~ sqrt(N) or const): tau -> C_par/gm ~ N.

    C_filt comes from specs.kick_filter, which reads TQ_SIM — so it is
    evaluated through sub() at the PDK's real chop grid, not the sim grid."""
    o = specs.ota(pdk)
    ca = specs.cal(pdk)
    c_filt = sub(pdk, t_q, lambda p: specs.kick_filter(p)[1])
    c_self = ca["c_ota_self"] * o["i_side"] / ca["i_side_ref"]
    A = c_filt + c_self
    ci, cp = c_int_n(pdk, N, route), c_par_vg(pdk, N)
    return (A * (ci + cp) / ci + cp) / o["gm_in"]


CONV_PER_TAU = 26.0   # conv_time = n_coarse*2*tau + sar; sar scales as
                      # 240ns * tau/30ns = 8 tau => 11*2 + 8 = 30 tau (derived,
                      # asserted exactly against specs at the N=16 anchor)


def conv_time_n(pdk, N, route, t_q):
    return CONV_PER_TAU * tau_absorb_n(pdk, N, route, t_q)


def csnr_n_db(pdk, N, route, base_db=CSNR_MEAS_DB):
    """CSNR vs N.

    route 'cint': no N-dependence to first order.  The N per-cell errors and
      the N signal contributions both add in power (27g1), the converter span
      tracks +-4 sigma ~ sqrt(N) so B_y stays 8 (law:bout), and a charge-
      redistribution column has no headroom term (27g1 'when it breaks' #2) and
      exits law:ir outright ("charge-domain columns pass no DC and exit this law
      entirely", sec_laws).  So CSNR(N) = CSNR(N0).
    route 'cu': C_u ~ 1/sqrt(N) => Pelgrom sigma_C/C ~ C_u^-1/2 ~ N^1/4
      => -20 log10(N/N0)^(1/4) = -5 log10(N/N0) dB, i.e. -1.5 dB per octave."""
    return base_db if route == "cint" else base_db - 5.0 * math.log10(N / N_PAPER)


def n_max_swing_fixed_cint():
    """Neither route taken: keep C_int AND C_u, just add rows.  The +-4 sigma
    full scale grows sqrt(N) and must stay under the MEASURED OTA compression
    ceiling MAC_MAX, from the CODE_MAX design point.  Anchor-free ratio:
        N_max/N_0 = (MAC_MAX/CODE_MAX)^2 = (185/120)^2 = 2.38
    Headroom is LINEAR in sigma but N enters as sqrt(N): 54% of headroom buys
    2.4x of rows and nothing more."""
    return (specs.MAC_MAX / specs.CODE_MAX) ** 2


def tile_area_mm2(pdk, N, M, route, a_conv=A_CONV_UM2):
    """law:convdens denominator: A_cells + M*A_conv + M*A_Cint + wrap."""
    a_cells = N * 2 * M * A_CELL_UM2                # differential: 2 banks/weight
    a_cint = M * c_int_n(pdk, N, route) * 1e15 / pdk.cap_density_mim
    return WRAP_MULT * (a_cells + M * a_conv + a_cint) / 1e6


def tile_point(pdk, t_q, N, M, K, route, gm_scaled=False):
    """One (N, M, K) operating point.  gm_scaled=True holds tau at the N=16
    anchor by scaling the OTA current with the virtual-ground load (buys the
    time back with STATIC POWER ~ N, so TOPS/W stays flat)."""
    conv = conv_time_n(pdk, N_ANCHOR if gm_scaled else N, route, t_q)
    tq = max(t_q, row_rc_tq_floor(pdk, M, n_seg=max(1, round(M / specs.N_COLS))))
    p = pass_time(tq, conv, K)
    f = 1.0 / p
    tops = 2 * N * M * f / 1e12
    area = tile_area_mm2(pdk, N, M, route)
    gm_mult = (tau_absorb_n(pdk, N, route, t_q) / tau_absorb_n(pdk, N_ANCHOR, route, t_q)
               if gm_scaled else 1.0)
    return {"N": N, "M": M, "K": K, "t_q": tq, "conv": conv, "pass": p,
            "f_mvm": f, "tops": tops, "area_mm2": area,
            "tops_mm2": tops / area, "csnr_db": csnr_n_db(pdk, N, route),
            "gm_mult": gm_mult, "bound": "window" if T_IN_TQ * tq >= conv / K
            else "conversion",
            "k_needed": conv / (T_IN_TQ * tq),
            "fj_per_mac_conv": E_ADC_PJ * 1e3 / (K * N)}


def k_star_needed_snr(K, target=CSNR_TARGET_DB, eg=specs.EG_SERVO):
    """Invert specs.parallel_cascade_snr_db: per-stage SNR that a K-deep
    parallel super-tile needs to still clear `target`.  inf if the fixed eg^2
    term alone already breaches it."""
    budget = 10.0 ** (-target / 10.0) - eg ** 2
    if budget <= 0:
        return float("inf")
    return -10.0 * math.log10(budget / K)


# ===========================================================================
# Q5 — node scaling, all constants named
# ===========================================================================
def node_scaling(from_nm, to_nm):
    """The three laws, stated as assumptions so they can be rejected.

    FREQUENCY
      systolic: f ~ 1/FO4(node).  Logic-delay limited.        -> IMPROVES
      ours    : f_MVM has no logic-delay term.  t_q is set by ROW WIRE RC
                = r_sq*(L/p)*(M*15*C_u + 0.2fF/um*L), and advanced nodes have
                HIGHER r_sq on a TIGHTER pitch -> t_q_floor gets WORSE.
                Measured in-model at M=17: sky130 8.5 ps -> N4 92 ps (11x
                worse).  conv_time improves (gm/C), t_q does not.
    ENERGY
      digital : E ~ C V^2 ~ node * V^2.                        -> IMPROVES
      ours    : the conversion floor is 12 kT 4^B_y (law:esnr) — "supply voltage
                cancels exactly, so process scaling does not help at fixed
                resolution".  And SNR_a FALLS 65 nm -> 7 nm (27g1).  -> FLAT/WORSE
    AREA
      digital : A_MAC ~ F^2.                                   -> IMPROVES
      ours    : the crosspoint is a BEOL cap whose area is set by MATCHING
                (Pelgrom sigma_C/C = A_C/sqrt(area)) at fixed CSNR, not by F.
                SERVO_EG.md: per-cell scatter 5.5% (sky130) -> 9.4% (N4) at the
                drawn C_u.                                     -> FLAT/WORSE
    Net: all three node-scaling laws favour the systolic array."""
    return {"f_systolic_x": FO4_PS[from_nm] / FO4_PS[to_nm],
            "f_ours_x": "see row-RC table (anti-scales)",
            "e_digital_x": "~node ratio (CV^2)",
            "e_ours_x": 1.0, "a_digital_x": (from_nm / to_nm) ** 2,
            "a_ours_x": 1.0}


# ===========================================================================
# report
# ===========================================================================
def build():
    L, P = [], TsmcN4Proj()
    specs._CAL[P.name] = P.cal_proj
    t_q = P.t_q_grid
    conv_n4 = sub(P, t_q, specs.conv_time)
    tau_n4 = sub(P, t_q, specs.tau_absorb)
    floors = {p.name: (row_rc_5rc(p, specs.N_COLS), p.jitter_budget_s)
              for p in (Sky130(), Asap7Proj(), P)}

    ap = L.append
    ap("# THROUGHPUT CEILING — can f_MVM reach 1 GHz, and can we beat a "
       "systolic array?")
    ap("")
    ap("Generated by `scripts/compiler/metrics/throughput_ceiling.py`. **No SPICE.** "
       "Pure parameter evaluation through `analog/schematics/specs.py` with the "
       "`pdk_projections.evaluate` runtime substitutions (per-PDK `TQ_SIM`; "
       "`sar_time` scaled by the `tau_absorb` ratio — forgetting the second one "
       "inflates N4 `conv_time` ~3x).")
    ap("")
    ap("Labels: **measured** = SPICE-backed; **derived** = arithmetic on "
       "measured/committed values; **projected** = model extrapolation; "
       "**ASSUMPTION** = a named constant at the top of the script that a "
       "reader must supply or reject.")
    ap("")

    ap("## Corrections to the framing, before any answer")
    ap("")
    ap("Three numbers in the question do not survive checking. Stating them "
       "first, because two of the six answers change sign if they are kept.")
    ap("")
    ap(f"1. **\"tile = 512x256 MACs in ~0.006 mm2\" — no.** `0.006 mm2` is "
       f"`pdk_projections.TILE_MM2['tsmc_n4_proj']`, and that table is paired "
       f"with `passes_per_token = 7e9/256`, i.e. **256 MACs/pass** — it is the "
       f"**16x16 MINI tile**, 512x smaller than a 512x256 array. The paper's "
       f"own 512x256 tile is 0.03-0.04 mm2 converged / 0.1 mm2 conservative "
       f"(`sec_eval.tex`). This model gets "
       f"{tile_area_mm2(P, N_PAPER, M_PAPER, 'cint'):.3f} mm2 — larger than the "
       f"paper, because the +-4 sigma swing law makes C_int "
       f"({c_int_n(P, N_PAPER, 'cint')*1e15:.0f} fF/column = "
       f"{c_int_n(P, N_PAPER, 'cint')*1e15/P.cap_density_mim:.0f} um2) the "
       f"**largest single item in the tile at N=512**, bigger than the "
       f"crosspoint array itself. Using 0.006 mm2 for a 512x256 tile inflates "
       f"TOPS/mm2 by ~9x. _(derived)_")
    ap(f"2. **\"t_q floor ~75-90 ps at N4\" — 92-97 ps, and only at M=17.** The "
       f"floor is `5*R_row*C_row` on a wire that crosses M COLUMNS, so it goes "
       f"as M^2. At the 256-column tile the question is about, an unsegmented "
       f"row gives **{row_rc_5rc(P, 256, 1)*1e9:.0f} ns**, not 92 ps (Q3, last "
       f"table). _(derived)_")
    ap(f"3. **\"0.8-5.7 TOPS/tile\" silently assumes tau_absorb is "
       f"N-independent.** It is not: all N banks land on the OTA virtual "
       f"ground, so `tau ~ N`. Without buying the time back with OTA current, "
       f"the honest N=512 number is "
       f"{tile_point(P, t_q, N_PAPER, M_PAPER, 1, 'cint')['tops']:.2f} "
       f"TOPS/tile, not "
       f"{tile_point(P, t_q, N_PAPER, M_PAPER, 1, 'cint', gm_scaled=True)['tops']:.2f}. "
       f"Q3 is the whole argument. _(derived)_")
    ap("")

    # ---------------- Q1 ----------------
    ap("## Q1 — What sets f_MVM, and its hard floor")
    ap("")
    ap("```")
    ap("pass(K) = max( T_in , T_conv/K ) + 4 t_q      f_MVM = 1/pass")
    ap("T_in    = 136 t_q   (128-cycle merged PWM window + 8 settle-in)")
    ap("T_conv  = n_coarse * 2*tau_absorb + t_SAR  =  26 * tau_absorb")
    ap("           (n_coarse=11, cadence = K_SETTLE*tau = 2 tau, "
       "t_SAR = 240ns * tau/30ns = 8 tau)")
    ap("```")
    ap(f"At N4, t_q = {t_q*1e12:.0f} ps: T_in = **{T_IN_TQ*t_q*1e9:.2f} ns**, "
       f"tau_absorb = {tau_n4*1e9:.3f} ns, T_conv = **{conv_n4*1e9:.2f} ns** "
       f"_(derived)_.")
    ap("")
    ap(f"- **K=1 (the only K the measured {CSNR_MEAS_DB} dB CSNR supports): "
       f"CONVERSION binds**, by {conv_n4/(T_IN_TQ*t_q):.1f}x. "
       f"f_MVM = {1e-6/pass_time(t_q, conv_n4, 1):.1f} MHz _(projected)_.")
    ap(f"- **K -> inf: the PWM WINDOW binds**, hard. pass -> 140 t_q. "
       f"f_MVM -> {1e-6/pass_time(t_q, conv_n4, 1000):.1f} MHz at "
       f"t_q = {t_q*1e12:.0f} ps _(projected)_.")
    ap(f"- Flip point: K = T_conv/T_in = **{conv_n4/(T_IN_TQ*t_q):.1f}** "
       f"(i.e. K >= 9). Past that, conv_time work buys exactly zero _(derived)_.")
    ap("")
    ap(f"### Is 1 GHz reachable? **No — by {max(floors['tsmc_n4_proj'])/tq_for_fmvm(1e9):.0f}x, and the blocker is a WIRE, not a transistor.**")
    ap("")
    ap(f"1 GHz => pass = 1 ns = 140 t_q => **t_q = "
       f"{tq_for_fmvm(1e9)*1e12:.2f} ps** _(derived)_. The user's 7 ps estimate "
       f"is right.")
    ap("")
    ap("`specs.t_q_floor` is `max(5*R_row*C_row, jitter_budget)` — a ROW-WIRE "
       "distributed-RC transit, not a device delay:")
    ap("")
    ap("| PDK | row RC (5RC, M=17) | jitter budget | t_q floor | 1 GHz needs | short by |")
    ap("|---|---|---|---|---|---|")
    for name, (rc, jit) in floors.items():
        fl = max(rc, jit)
        ap(f"| {name} | {rc*1e12:.1f} ps | {jit*1e12:.0f} ps | "
           f"**{fl*1e12:.0f} ps** | {tq_for_fmvm(1e9)*1e12:.1f} ps | "
           f"**{fl/tq_for_fmvm(1e9):.0f}x** |")
    ap("")
    ap("Two things that kill the 1 GHz idea outright _(derived)_:")
    ap("")
    ap(f"1. **t_q is a BEOL RC transit, so a faster transistor does not touch "
       f"it.** The 7.1 ps target is {max(floors['tsmc_n4_proj'])/tq_for_fmvm(1e9):.0f}x "
       f"below the N4 floor. There is no bias current, no topology and no "
       f"device that buys it back.")
    ap(f"2. **Row RC ANTI-SCALES with the node.** sky130 (130 nm, fat slow "
       f"metal) 5RC = {floors['sky130'][0]*1e12:.1f} ps; N4 "
       f"{floors['tsmc_n4_proj'][0]*1e12:.0f} ps — "
       f"**{floors['tsmc_n4_proj'][0]/floors['sky130'][0]:.0f}x WORSE at the "
       f"newer node**, because r_sq rises (3.0 vs 0.125 ohm/sq) faster than the "
       f"pitch and C_u fall. Shrinking the process to chase 1 GHz moves t_q the "
       f"wrong way.")
    ap("")
    fmax = 1.0 / (PASS_TQ_FLOOR * max(floors["tsmc_n4_proj"]))
    ap(f"**Honest speed ceiling of this architecture (K -> inf, t_q at the true "
       f"row-RC floor, M=17): f_MVM_max = 1/(140 * "
       f"{max(floors['tsmc_n4_proj'])*1e12:.0f} ps) = "
       f"{fmax/1e6:.1f} MHz** _(projected)_ — **{1e9/fmax:.1f}x short of 1 GHz**, "
       f"and that already assumes a K the CSNR does not support. At the running "
       f"t_q = 100 ps the ceiling is "
       f"{1e-6/(PASS_TQ_FLOOR*t_q):.1f} MHz.")
    ap("")

    # ---------------- Q2 ----------------
    s = systolic(SYS["rows"], SYS["cols"], SYS["f_hz"])
    ours_k1 = tile_point(P, t_q, N_ANCHOR, M_PAPER, 1, "cint")
    ours_k1_gm = tile_point(P, t_q, N_PAPER, M_PAPER, 1, "cint", gm_scaled=True)
    ap("## Q2 — f_MVM is NOT the systolic clock. The comparison is not "
       "like-for-like.")
    ap("")
    ap(f"{SYS['name']} at {SYS['f_hz']/1e6:.0f} MHz _({SYS['label']})_ retires "
       f"**one MAC per PE per cycle**. Our f_MVM retires a **complete "
       f"{N_PAPER}x{M_PAPER} MVM** — {2*N_PAPER*M_PAPER:,} ops per tick vs "
       f"{2*SYS['rows']*SYS['cols']:,}. Putting "
       f"{1e-6/ours_k1_gm['pass']:.0f} MHz next to "
       f"{SYS['f_hz']/1e6:.0f} MHz is a category error: the units are "
       f"MVMs/s on one side and MACs/PE/s on the other. Do it properly, "
       f"three scoreboards:")
    ap("")
    ap("| scoreboard | when it is the right one | systolic 256x256 @940 MHz | "
       "note |")
    ap("|---|---|---|---|")
    ap(f"| **peak TOPS** | batched GEMM, weights resident, B >> 256 | "
       f"**{s['peak_tops']:.0f} TOPS** | marketing number; needs B >> 256 to "
       f"approach |")
    ap(f"| **batch-1 GEMV latency** | decode | "
       f"{s['b1_latency_s']*1e9:.0f} ns ({s['b1_cycles']} cycles: "
       f"{SYS['rows']} skew-in + {SYS['cols']} drain + 1) | fill/drain is the "
       f"whole cost |")
    ap(f"| **batch-1 effective MACs/s** | decode | "
       f"**{s['b1_tops']:.2f} TOPS** (util **{s['b1_util']*100:.2f}%**) | "
       f"{s['peak_tops']/s['b1_tops']:.0f}x below peak |")
    ap(f"| + weight load ({SYS['rows']} cyc/new tile) | decode, model >> array | "
       f"**{s['b1_tops_wload']:.2f} TOPS** | every tile is new at 7B/batch-1 |")
    ap("")
    ap("**Which scoreboard for which regime** (`law:roofline`, `law:batch`):")
    ap("")
    ap("- `law:roofline`: arithmetic intensity is `I_w = B/b_w` — *dimensions "
       "cancel*, so enlarging the layer cannot rescue a small batch. At B=1 the "
       "digital machine is BANDWIDTH-bound and its peak TOPS is not the "
       "scoreboard at all; `Q/beta` is. Analog residency sends `Q -> 0`. **Right "
       "scoreboard for decode: MVM latency and tok/s, not TOPS.**")
    ap("- `law:batch`: analog stationary-weight compute has strictly linear "
       "batch cost `t(B) = B t_MVM`; the digital weight-traffic term falls as "
       "1/B. As B rises the comparison collapses to pure energy/op and area/op "
       "at matched precision — *both decided by the converter*. **Right "
       "scoreboard for batched GEMM: TOPS/mm2 and TOPS/W, and analog gets no "
       "batch economy to help it.**")
    ap("")
    ap(f"Our side, same three (N={N_PAPER}, M={M_PAPER}, K=1, OTA current scaled "
       f"to hold tau — see Q3): peak = batch-1 = "
       f"**{ours_k1_gm['tops']:.2f} TOPS**, MVM latency "
       f"**{ours_k1_gm['pass']*1e9:.0f} ns** for {2*N_PAPER*M_PAPER:,} ops "
       f"_(projected)_. Against the systolic that is "
       f"**{ours_k1_gm['tops']/s['peak_tops']:.3f}x on peak** and "
       f"**{ours_k1_gm['tops']/s['b1_tops']:.1f}x on batch-1** — the *entire* "
       f"sign flip is the systolic's 0.2% fill/drain utilisation, not our clock.")
    ap("")

    # ---------------- Q3 ----------------
    ap("## Q3 — Raise N, not frequency. Where the N win actually stops.")
    ap("")
    ap("### The premise is right, and two of the three laws do exit")
    ap("")
    ap("- `law:mac` / Kirchhoff: the column accumulates all N rows in **one "
       "settling event**, so T_in and T_conv contain no N. `TOPS = 2 N M f_MVM` "
       "with f_MVM nominally N-free. **Correct.**")
    ap("- `law:bout`: B_y ~ 8 **independent of N** — the dot product concentrates "
       "to sqrt(N), so clipping at +-4 sigma keeps the converter at 8 b forever. "
       "The converter does NOT grow with N. **Correct, and it is the key "
       "enabler.**")
    ap("- `law:ir`: verbatim from `sec_laws.tex` — *\"Charge-domain columns pass "
       "no DC and exit this law entirely\"* (cites chen2021capram, "
       "bhardwaj2025toward). The N ~ 64-512 pin on resistive IMC **does not "
       "apply to us**. **Confirmed from the paper text.**")
    ap("- `27g1`: the 19.6 dB / N<=125 knee is a CHARGE-SUMMING bitline-headroom "
       "effect. Its own *When it breaks* #2: *\"Charge redistribution has no "
       "headroom term. In the QR compute model sigma_eta_h^2 = 0, so SNR_a does "
       "not collapse with N.\"* We are charge-redistribution onto a "
       "virtual-ground integrator. **The 125-row knee is not our knee.**")
    ap("")
    ap("### But there is a fourth constraint the question did not list, and it "
       "is the one that binds")
    ap("")
    ap("`analog/schematics/components/weight_tile/weight_tile.py`, verbatim:")
    ap("")
    ap("> *\"Column rails are the integrator virtual grounds (OTA inn nodes)\"* "
       "... *\"TG to the column rail during phi2 (transfer)\"*")
    ap("")
    ap(f"So **all N crosspoint banks land on the OTA virtual ground during the "
       f"very phi2 settling event `tau_absorb` measures**. `C_par_vg` is LINEAR "
       f"in N: {c_par_row(P)*1e15:.2f} fF/row at N4 "
       f"({C_BALL_SKY*1e15:.0f} fF top ballast cap-shrink-scaled + 15 C_u), on a "
       f"{max(0.0, specs.cal(P)['c_par_vg'] - N_ANCHOR*c_par_row(P))*1e15:.0f} fF "
       f"fixed C_RAIL/wire base _(derived from the committed _CAL value at "
       f"N={N_ANCHOR})_.")
    ap("")
    ap("Closed form, from `specs.tau_absorb` with `beta = C_int/(C_int+C_par)`:")
    ap("")
    ap("```")
    ap("tau_absorb * gm_in = A + A*C_par(N)/C_int(N) + C_par(N),   "
       "A = C_filt + C_ota_self")
    ap("C_par(N) ~ N   and   C_int(N) ~ sqrt(N)  =>  tau ~ N   =>  T_conv ~ N")
    ap("=> conversion-bound TOPS = 2*N*M/T_conv(N)  ->  CONSTANT in N.")
    ap("```")
    ap("")
    ap("**The N win and the OTA-loading loss are the same order and cancel.** "
       "That is the honest answer to Q3 and it is not what the note expected.")
    ap("")
    ap("### Swing / charge headroom — the anchor-free number")
    ap("")
    ap(f"With C_int AND C_u both held (just add rows): the +-4 sigma full scale "
       f"grows as sqrt(N) and must stay under the **measured** OTA compression "
       f"ceiling `MAC_MAX = {specs.MAC_MAX}` from the `CODE_MAX = "
       f"{specs.CODE_MAX}` design point:")
    ap("")
    ap(f"> **N_max / N_0 = (MAC_MAX/CODE_MAX)^2 = ({specs.MAC_MAX}/"
       f"{specs.CODE_MAX})^2 = {n_max_swing_fixed_cint():.2f}x** _(derived, "
       f"anchor-free)_")
    ap("")
    ap(f"54% of spare headroom buys **2.4x of rows and nothing more**, because "
       f"headroom is linear in sigma and N enters as sqrt(N). To go 8x in N one "
       f"of C_int or C_u must move, and each has a price:")
    ap("")
    ap("| route | what moves | price | binds at |")
    ap("|---|---|---|---|")
    ap("| **A** `cu` | C_u ~ 1/sqrt(N), C_int fixed | Pelgrom "
       "`sigma_C/C ~ C_u^-1/2 ~ N^1/4` => **-1.5 dB CSNR per octave of N** | "
       "CSNR |")
    ap("| **B** `cint` | C_int ~ sqrt(N), C_u fixed | MOM area ~sqrt(N)/column "
       "**and** tau_absorb ~ N | area + conv_time |")
    ap("| C | neither | clipping | 2.4x, hard |")
    ap("")
    n_a = N_PAPER * 10 ** ((CSNR_MEAS_DB - CSNR_TARGET_DB) / 5.0)
    n_a34 = N_PAPER * 10 ** ((CSNR_HYPO_DB - CSNR_TARGET_DB) / 5.0)
    ap(f"**Route A max N** (solve `CSNR - 5 log10(N/N_0) >= "
       f"{CSNR_TARGET_DB}`), from N_0 = {N_PAPER}:")
    ap("")
    ap(f"- at the **measured {CSNR_MEAS_DB} dB**: N <= **{n_a:.0f}** "
       f"({n_a/N_PAPER:.2f}x) — 0.5 dB of margin is **a quarter of an octave**. "
       f"_(projected)_")
    ap(f"- at a hypothetical **{CSNR_HYPO_DB} dB**: N <= **{n_a34:.0f}** "
       f"({n_a34/N_PAPER:.1f}x). _(projected)_")
    ap("")
    ap("### The N sweep, route B (the generous one), N4")
    ap("")
    ap("| N | C_int/col | C_par_vg | tau_absorb | T_conv | K=1 TOPS/tile | "
       "area mm2 | TOPS/mm2 | conv fJ/MAC | K for window-bound | per-stage SNR "
       "that K needs |")
    ap("|---|---|---|---|---|---|---|---|---|---|---|")
    sweep = [16, 64, 128, 256, 512, 1024, 2048, 4096]
    rows_b = {}
    for N in sweep:
        r = tile_point(P, t_q, N, M_PAPER, 1, "cint")
        rows_b[N] = r
        kn = math.ceil(r["k_needed"])
        need = k_star_needed_snr(kn)
        ap(f"| {N} | {c_int_n(P, N, 'cint')*1e15:.0f} fF | "
           f"{c_par_vg(P, N)*1e12:.2f} pF | {tau_absorb_n(P, N, 'cint', t_q)*1e9:.1f} ns "
           f"| {r['conv']*1e9:.0f} ns | **{r['tops']:.3f}** | "
           f"{r['area_mm2']:.4f} | {r['tops_mm2']:.1f} | "
           f"{r['fj_per_mac_conv']:.2f} | {kn} | "
           f"{need:.1f} dB (have {CSNR_MEAS_DB}) |")
    ap("")
    g512, g4096 = rows_b[512], rows_b[4096]
    ap(f"**Read-off _(projected)_.** N = 512 -> 4096 is 8x the MACs and buys "
       f"**{g4096['tops']/g512['tops']:.2f}x TOPS** at K=1 — the OTA "
       f"virtual-ground load eats "
       f"{100*(1 - (g4096['tops']/g512['tops'])/8):.0f}% of it. The two things "
       f"that DO improve monotonically are the ones `law:convdens` cares about: "
       f"conversion energy per MAC "
       f"({g512['fj_per_mac_conv']:.2f} -> {g4096['fj_per_mac_conv']:.2f} fJ/MAC, "
       f"c = 1/N) and converter-area amortisation. **TOPS/tile is not one of "
       f"them.**")
    ap("")
    ap("### The only way N buys TOPS: pay for it in static power")
    ap("")
    ap("tau = C_out_eff/(beta*gm_in) and gm_in ~ I_side. Hold tau at the N=16 "
       "value by scaling the OTA current with the load:")
    ap("")
    ap("| N | gm/current multiple | TOPS/tile | tile OTA static | TOPS/W (static "
       "only) | area mm2 | TOPS/mm2 |")
    ap("|---|---|---|---|---|---|---|")
    for N in (512, 1024, 2048, 4096):
        r = tile_point(P, t_q, N, M_PAPER, 1, "cint", gm_scaled=True)
        p_w = M_PAPER * 2 * specs.I_SIDE * r["gm_mult"] * P.vdd
        ap(f"| {N} | {r['gm_mult']:.1f}x | **{r['tops']:.2f}** | "
           f"{p_w*1e3:.1f} mW | {r['tops']/p_w:.0f} | {r['area_mm2']:.3f} | "
           f"{r['tops_mm2']:.0f} |")
    ap("")
    ap("**TOPS ~ N, power ~ N, area ~ N => TOPS/W and TOPS/mm2 are FLAT.** N is "
       "a *scale* knob (buy more silicon, get more throughput), not an "
       "*efficiency* knob — exactly like adding PEs to a systolic array. The one "
       "thing it genuinely improves is `c = conversions/MAC = 1/N`, which is the "
       "`law:convdens` objective. That is real but it is a J/MAC win, not a "
       "TOPS win.")
    ap("")
    ap("### Wire-RC feedback: it is on M, not N — and it is brutal")
    ap("")
    ap("A row wire crosses COLUMNS. `specs.t_q_floor` has `R ~ M` and `C ~ M`, "
       "so **t_q_floor ~ M^2 and contains no N at all.** Growing N is free in "
       "t_q; growing M is quadratic:")
    ap("")
    ap("| M (columns on one row wire) | unsegmented 5RC | with 1 re-driver per "
       "17 cols | ")
    ap("|---|---|---|")
    for M in (17, 64, 128, 256, 512):
        seg = max(1, round(M / specs.N_COLS))
        ap(f"| {M} | {row_rc_5rc(P, M, 1)*1e12:,.0f} ps | "
           f"{row_rc_5rc(P, M, seg)*1e12:.0f} ps |")
    ap("")
    ap(f"**Loud correction to the paper's own design point.** `sec_eval.tex` "
       f"states t_q = 200 ps at N=512, M=256. The row-RC model in `specs.py` "
       f"gives **{row_rc_5rc(P, 256, 1)*1e9:.1f} ns** for an unsegmented "
       f"256-column row at N4 (and "
       f"{row_rc_5rc(Sky130(), 256, 1)*1e9:.1f} ns even on sky130's fat "
       f"metal) — **{row_rc_5rc(P, 256, 1)/200e-12:,.0f}x** the assumed "
       f"value. The 512x256 tile is only buildable at 100 ps as ~15 "
       f"locally re-driven row segments of ~17 columns. That is an architectural "
       f"requirement, not a layout detail, and the re-drivers re-enter as edge "
       f"skew (`sec_circuits`: *\"Edge skew across 512 rows enters as input "
       f"error\"*). _(derived; flagged for the paper)_")
    ap("")

    # ---------------- Q4 ----------------
    ap("## Q4 — Other throughput levers, scored")
    ap("")
    w6 = 72 * t_q
    ap("| # | lever | mechanism | worth at K=1 (conversion-bound, TODAY) | "
       "worth at K>=9 (window-bound) | CSNR cost | verdict |")
    ap("|---|---|---|---|---|---|---|")
    ap(f"| 1 | **N: 512 -> 4096** (route B) | more rows, same settling event | "
       f"**{g4096['tops']/g512['tops']:.2f}x** TOPS (OTA load cancels 8x -> "
       f"{g4096['tops']/g512['tops']:.2f}x) | 8x TOPS *if* K ~ "
       f"{math.ceil(g4096['k_needed'])} were reachable | 0 dB route B / "
       f"-4.5 dB route A | **scale knob, not efficiency**; buys J/MAC + "
       f"TOPS/mm2, not TOPS/W |")
    ap(f"| 2 | N + gm ~ N | buy the settling time back with current | "
       f"**8x** TOPS | 8x | 0 dB | works, but power ~ N: **TOPS/W flat** |")
    ap(f"| 3 | `b_x` 7 -> 6 (window 136 -> 72 t_q) | halves T_in | "
       f"**0.0x — exactly zero**; T_in is not the max() term ("
       f"{T_IN_TQ*t_q*1e9:.1f} vs {conv_n4*1e9:.0f} ns) | "
       f"{pass_time(t_q,conv_n4,1000)/(76*t_q):.2f}x | **-6 dB SQNR_i**, and "
       f"CSNR is the binding constraint | **strictly negative today** |")
    ap(f"| 4 | more M (columns/tile) | linear MACs, linear converters | "
       f"linear TOPS but linear area | same | 0 dB | **`law:convdens` gives NO "
       f"optimum M**: numerator `f*N*M` and denominator "
       f"`A_cells(~NM) + M*A_conv` are BOTH linear in M, so TOPS/mm2 is "
       f"M-invariant. The only M-dependence anywhere is the row wire: "
       f"**t_q ~ (M/n_seg)^2**. M is a packaging choice, not a lever |")
    ap(f"| 5 | deeper pipelining past ping-pong | overlap window/conversion | "
       f"already in the `max()` | **0x — the window IS the floor** | 0 dB | "
       f"nothing left |")
    ap(f"| 6 | more ADCs/tile (S converters/column) | S conversions in flight | "
       f"divides T_conv by S, up to the {conv_n4/(T_IN_TQ*t_q):.1f}x window "
       f"floor: max **{conv_n4/(T_IN_TQ*t_q):.1f}x** | 0x | 0 dB | *the best "
       f"CSNR-free time lever* — S=8 gets window-bound with **no K, no dB**; "
       f"cost is `M*A_conv*S` area (`law:convdens` denominator) |")
    ap(f"| 7 | conv_time engineering (K_SETTLE, n_coarse, SAR) | shrinks "
       f"T_conv | up to {conv_n4/(T_IN_TQ*t_q):.1f}x, full elasticity | 0x | "
       f"0 dB | real runway at K=1 (CONVTIME_SENSITIVITY.md) |")
    ap(f"| 8 | +CSNR (dB) | unlocks K | K=2 at "
       f"{k_star_needed_snr(2):.1f} dB, K=9 at {k_star_needed_snr(9):.1f} dB | "
       f"— | — | **{k_star_needed_snr(9)-CSNR_MEAS_DB:.1f} dB short** of the "
       f"window-bound point |")
    ap("")
    ap("**Ranked (raw TOPS at the honest K=1):** (6) more converters per "
       "tile > (7) conv_time > (2) N+gm [scale, flat efficiency] > (1) N alone "
       "> (8) CSNR [highest value, furthest away] >> (4) M [exactly 1.00x on "
       "TOPS/mm2] > (5) pipelining [0x] > (3) b_x [0x and -6 dB].")
    ap("")
    ap("The lever the question expected to win — raise N — is #1 only for "
       "`law:convdens` (J/MAC, TOPS/mm2). For raw TOPS it is beaten by simply "
       "putting more converters on the tile, because at K=1 the bottleneck is "
       "the conversion and N does not shorten it (it lengthens it).")
    ap("")

    # ---------------- Q5 ----------------
    ap("## Q5 — Matched-PDK comparison. The 28 nm confound is REAL, and it "
       "flatters us.")
    ap("")
    ap(f"The {SYS['f_hz']/1e6:.0f} MHz 256x256 reference is **{SYS['node_nm']} "
       f"nm** ({SYS['label']}); our projection is N4. Three nodes of confound. "
       f"Node-scaling law used (all **ASSUMPTION**, stated so it can be "
       f"rejected):")
    ap("")
    ap("| axis | systolic / digital | AnalogIOC | direction |")
    ap("|---|---|---|---|")
    ns = node_scaling(28, 4)
    ap(f"| frequency | `f ~ 1/FO4(node)`; FO4 {FO4_PS[28]} -> {FO4_PS[4]} ps "
       f"=> **{ns['f_systolic_x']:.1f}x** | `f_MVM` has NO logic-delay term. "
       f"t_q = row-wire RC, and `r_sq` RISES faster than pitch and C_u fall: "
       f"sky130 {floors['sky130'][0]*1e12:.1f} ps -> N4 "
       f"{floors['tsmc_n4_proj'][0]*1e12:.0f} ps = "
       f"**{floors['tsmc_n4_proj'][0]/floors['sky130'][0]:.0f}x WORSE** "
       f"(conv_time DOES improve: tau_absorb {sub(Sky130(), 200e-12, specs.tau_absorb)*1e9:.1f} -> {tau_n4:.2e}".replace(f"{tau_n4:.2e}", f"{tau_n4*1e9:.2f} ns = {sub(Sky130(), 200e-12, specs.tau_absorb)/tau_n4:.1f}x better") + f") | **against "
       f"us** |")
    ap("| energy | `E ~ C V^2` improves with the node | `law:esnr`: the "
       "conversion floor is `12 kT 4^B_y` and *\"supply voltage cancels "
       "exactly, so process scaling does not help at fixed resolution\"*. "
       "`27g1`: SNR_a FALLS 65 -> 7 nm; energy at fixed SNR_pre is *higher* at "
       "11/7 nm than at 22 nm | **against us** |")
    ap(f"| area | `A_MAC ~ F^2` => **{ns['a_digital_x']:.0f}x** 28 -> 4 nm | "
       f"the crosspoint is a BEOL cap sized by MATCHING "
       f"(`sigma_C/C = A_C/sqrt(area)`), not by F. SERVO_EG.md per-cell "
       f"scatter {PELGROM_CELL['sky130']*100:.1f}% (sky130) -> "
       f"{PELGROM_CELL['tsmc_n4_proj']*100:.1f}% (N4) at the drawn C_u | "
       f"**against us** |")
    ap("")
    ap("> **All three node-scaling laws favour the systolic array.** Answering "
       "the user's question honestly *hurts* our case: comparing our N4 "
       "projection to a 28 nm TPUv1 was the flattering direction, not the "
       "unfair one.")
    ap("")
    ap("**(a) Our architecture at a 28 nm-class node.** I will not interpolate. "
       "`specs.py` re-derives from `r_sq_wire`, `wire_pitch`, `vdd`, "
       "`cap_density_mim`, `c_int_col`, `jitter_budget_s` and a gm/ID table; "
       "there is no 28 nm `PDKConfig` in `library/pdks/` (sky130=130 nm, "
       "asap7=7 nm, tsmc_n4=4/5 nm) and the gm/ID tables are sky130-only "
       "(`specs.ota` widths are meaningless off sky130 — flagged in "
       "PDK_PROJECTIONS.md's own O1b list). What CAN be said without inventing "
       "constants: the row-RC term would land **between** sky130's "
       f"{floors['sky130'][0]*1e12:.1f} ps and asap7's "
       f"{floors['asap7_proj'][0]*1e12:.0f} ps, so t_q at 28 nm would be "
       f"**jitter-bound, not RC-bound** — i.e. 28 nm is a *better* node for our "
       f"t_q than N4 is. _(derived from the two bracketing PDKs; the 28 nm point "
       f"itself is NOT computed.)_")
    ap("")
    ap("**(b) A systolic array at N4.** Framework only, constants named:")
    ap("")
    ap("```python")
    ap("SYS_N4 = {'rows': ?, 'cols': ?, 'f_hz': ?}   # fill from the lit agent")
    ap("peak_tops = 2 * rows * cols * f_hz")
    ap("b1_tops   = 2 * rows * cols / ((rows + cols + 1) / f_hz)")
    ap("# our matched point is already at N4, so ONLY these three move.")
    ap("```")
    ap("")
    ap("Sensitivity, so the answer is known before the constants arrive: our "
       f"best N4 point is **{ours_k1_gm['tops']:.2f} TOPS/tile**. A systolic "
       f"array reaches that on peak with `rows*cols*f = "
       f"{ours_k1_gm['tops']*1e12/2:.3g}` — e.g. 256x256 at "
       f"{ours_k1_gm['tops']*1e12/2/(256*256)/1e6:.0f} MHz. **Any plausible N4 "
       f"systolic beats us on peak TOPS by 1-2 orders of magnitude.** The "
       f"crossover is on batch-1 utilisation and on J/MAC, and neither depends "
       f"on the constants we are waiting for.")
    ap("")

    # ---------------- Q6 ----------------
    ap("## Q6 — Verdict, per regime")
    ap("")
    ap(f"### (i) Batched GEMM — **NO, by construction.**")
    ap("")
    ap("`law:batch`, stated exactly: *analog stationary-weight compute has "
       "strictly linear batch cost `t(B) = B t_MVM` per tile or B x replicated "
       "tiles; a digital machine's weight-traffic term falls as 1/B*. **Analog "
       "gets no batch economy.** As B rises the digital array walks right along "
       "the roofline until it is compute-bound at its peak; we stay at "
       "`B * t_MVM`. Numerically:")
    ap("")
    ap(f"- ours, best N4 point: **{ours_k1_gm['tops']:.2f} TOPS/tile** "
       f"(N={N_PAPER}, M={M_PAPER}, K=1, gm ~ N) _(projected)_")
    ap(f"- ours, window-bound ceiling (K -> inf, needs "
       f"{k_star_needed_snr(9):.1f} dB CSNR we do not have): "
       f"{2*N_PAPER*M_PAPER*fmax/1e12:.1f} TOPS/tile _(projected, "
       f"NOT reachable at the measured CSNR)_")
    ap(f"- systolic 256x256 @940 MHz: **{s['peak_tops']:.0f} TOPS** _(vendor)_ "
       f"-> we are **{s['peak_tops']/ours_k1_gm['tops']:.0f}x short**, and "
       f"{s['peak_tops']/(2*N_PAPER*M_PAPER*fmax/1e12):.0f}x short even at the "
       f"unreachable ceiling")
    ap("- and every node-scaling law (Q5) moves that gap **wider**, not "
       "narrower.")
    ap("")
    ap("**Large N does NOT flip this.** It cannot, for two independent reasons: "
       "(a) at K=1 the OTA virtual-ground load makes `T_conv ~ N`, so the 8x "
       f"cancels to {g4096['tops']/g512['tops']:.2f}x; (b) buying the time back "
       "with `gm ~ N` gives TOPS ~ N at power ~ N and area ~ N — flat TOPS/W and "
       "flat TOPS/mm2, which is exactly what adding PEs does for the systolic "
       "array too. There is no structural advantage in the batched-GEMM regime. "
       "**Say it plainly: we lose (i), by construction, and no amount of N "
       "changes that.**")
    ap("")
    ap("### (ii) Batch-1 decode GEMV — **YES, and it is not close.**")
    ap("")
    ap("| | systolic 256x256 @940 MHz | AnalogIOC N4 (N=512, M=256, K=1) | ratio |")
    ap("|---|---|---|---|")
    ap(f"| MVM latency | {s['b1_latency_s']*1e9:.0f} ns for "
       f"{2*s['macs']:,} ops | {ours_k1_gm['pass']*1e9:.0f} ns for "
       f"{2*N_PAPER*M_PAPER:,} ops | "
       f"**{s['b1_latency_s']/ours_k1_gm['pass']:.1f}x** |")
    ap(f"| effective TOPS | {s['b1_tops']:.2f} | {ours_k1_gm['tops']:.2f} | "
       f"**{ours_k1_gm['tops']/s['b1_tops']:.1f}x** |")
    ap(f"| + weight load | {s['b1_tops_wload']:.2f} | {ours_k1_gm['tops']:.2f} "
       f"(weights RESIDENT, Q -> 0) | "
       f"**{ours_k1_gm['tops']/s['b1_tops_wload']:.1f}x** |")
    ap(f"| utilisation | **{s['b1_util']*100:.2f}%** | **100%** (one pass = one "
       f"complete MVM, no fill, no drain) | "
       f"{1/s['b1_util']:.0f}x |")
    ap("")
    ap("The mechanism is entirely the systolic array's own pipeline: "
       f"{SYS['rows']}+{SYS['cols']}+1 = {s['b1_cycles']} cycles of fill and "
       f"drain to retire one GEMV. And `law:roofline` says the real batch-1 "
       f"limit is not even that: at `I_w = B/b_w = 1` the digital machine is "
       f"BANDWIDTH-bound (`Q/beta`), and *dimensions cancel* — a bigger model "
       f"does not help. Analog residency deletes `Q`. **This is where the "
       f"architecture is supposed to win, and it does.**")
    ap("")
    ap("### The caveat that outranks all of it")
    ap("")
    ap(f"The **{CSNR_MEAS_DB} dB** held-out CSNR is from **nominal SPICE** — "
       f"`tb_csnr.py` says so in its own docstring: *\"the tt corner carries no "
       f"mismatch, and the tile's caps are ideal C elements anyway\"*. The "
       f"Pelgrom per-cell unit-cap scatter is an **additive, un-servoable** "
       f"term (SERVO_EG.md 1(c)) worth "
       f"{-20*math.log10(PELGROM_CELL['sky130']):.1f} dB on its own at sky130's "
       f"C_u and {-20*math.log10(PELGROM_CELL['tsmc_n4_proj']):.1f} dB at N4's. "
       f"Powers add:")
    ap("")
    for k, sig in PELGROM_CELL.items():
        tot = -10 * math.log10(10 ** (-CSNR_MEAS_DB / 10) + sig ** 2)
        ap(f"- {k} (C_u = {specs.c_u({'sky130': Sky130(), 'asap7_proj': Asap7Proj(), 'tsmc_n4_proj': P}[k])*1e15:.2f} fF): "
           f"{CSNR_MEAS_DB} dB (+) {-20*math.log10(sig):.1f} dB Pelgrom = "
           f"**{tot:.1f} dB** vs the {CSNR_TARGET_DB} dB target -> "
           f"{'PASS' if tot >= CSNR_TARGET_DB else '**FAIL by %.1f dB**' % (CSNR_TARGET_DB - tot)}")
    ap("")
    ap("**So even K=1 is not established at the advanced nodes**, and route A "
       "(shrink C_u to grow N) makes it strictly worse. Any large-N plan must "
       "go via route B (grow C_int), which is the one that pays in tau_absorb.")
    ap("")

    # ---------------- SPICE asks ----------------
    ap("## SPICE measurements this analysis needs (specified, not run)")
    ap("")
    ap("1. **`tau_absorb` vs virtual-ground load.** Sweep the C_par_vg lumped "
       "cap on the OTA inn node over 80 fF / 320 fF / 1.28 pF / 5.1 pF (= N = "
       "16/64/256/1024 at the derived 3.75 fF/row) and measure tau_absorb for "
       "each. **This single sweep decides Q3.** If tau grows sub-linearly the "
       "N verdict flips positive; the model says linear.")
    ap("2. **Monte-Carlo Pelgrom on `tb_csnr uncorr`.** Inject "
       "`sigma_C/C = A_C/sqrt(C_u/rho)` per unit cap (A_C = 1.0-1.5 %*um), 100 "
       "seeds, re-score attention CSNR. Decides whether 28.5 dB survives at all "
       "— see the last section.")
    ap("3. **`MAC_MAX` at raised V_SWING.** MAC_MAX = 185 is measured at the "
       "current swing; the 2.38x N ceiling and the whole route-B C_int scaling "
       "hang on the OTA staying LINEAR there. `tb_ota` swing sweep.")
    ap("4. **Row-wire t_q with re-drivers.** A 256-column row segmented 16-ways "
       "with local re-drivers: does the edge land inside the 100 ps grid, and "
       "what is the segment-to-segment skew? Blocks the 512x256 tile entirely.")
    ap("")
    return "\n".join(L) + "\n"


# ===========================================================================
# self-check
# ===========================================================================
def _selfcheck():
    P = TsmcN4Proj()
    specs._CAL[P.name] = P.cal_proj
    t_q = P.t_q_grid
    ok = []

    def chk(name, cond, msg=""):
        ok.append((name, bool(cond), msg))
        print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + msg) if msg else ''}")

    print("throughput_ceiling self-check")

    # Q1: schedule law reproduces pdk_projections exactly.
    conv = sub(P, t_q, specs.conv_time)
    ref = sub(P, t_q, specs.pingpong_pass_time, t_q=t_q)
    chk("pass law == specs.pingpong_pass_time",
        abs(pass_time(t_q, conv, 1) - ref) < 1e-15,
        f"{pass_time(t_q, conv, 1)*1e9:.3f} vs {ref*1e9:.3f} ns")
    chk("N4 conv_time == 94.86 ns (sar scaled)", abs(conv - 94.86e-9) < 0.05e-9,
        f"{conv*1e9:.2f} ns")

    # 1 GHz.
    tq1g = tq_for_fmvm(1e9)
    chk("1 GHz needs t_q ~ 7.1 ps", abs(tq1g - 7.143e-12) < 0.05e-12,
        f"{tq1g*1e12:.2f} ps")
    fl = row_rc_tq_floor(P, specs.N_COLS)
    chk("1 GHz is >=10x below the N4 t_q floor", fl / tq1g >= 10,
        f"floor {fl*1e12:.0f} ps = {fl/tq1g:.1f}x the 1 GHz t_q")
    fmax = 1.0 / (PASS_TQ_FLOOR * fl)
    chk("honest f_MVM ceiling in 50-150 MHz", 50e6 < fmax < 150e6,
        f"{fmax/1e6:.1f} MHz (K -> inf, t_q at floor)")

    # row RC anti-scales with the node, and t_q floor is M^2 / N-free.
    chk("row RC WORSE at N4 than sky130 (anti-scaling)",
        row_rc_5rc(P, 17) > 5 * row_rc_5rc(Sky130(), 17),
        f"sky130 {row_rc_5rc(Sky130(),17)*1e12:.1f} ps -> N4 "
        f"{row_rc_5rc(P,17)*1e12:.0f} ps")
    r1, r2 = row_rc_5rc(P, 17, 1), row_rc_5rc(P, 34, 1)
    chk("t_q_floor ~ M^2", abs(r2 / r1 - 4.0) / 4.0 < 0.10, f"{r2/r1:.2f}x for 2x M")

    # Q2: systolic batch-1 utilisation.
    s = systolic(256, 256, 940e6)
    chk("systolic peak ~123 TOPS", abs(s["peak_tops"] - 123) < 3,
        f"{s['peak_tops']:.1f} TOPS")
    chk("systolic batch-1 utilisation < 0.25%", s["b1_util"] < 0.0025,
        f"{s['b1_util']*100:.3f}% ({s['b1_cycles']} cycles/GEMV)")

    # Q3: conv_time == 30*tau identity, and the N cancellation.
    chk("conv_time == 26 * tau_absorb (exact)",
        abs(conv / sub(P, t_q, specs.tau_absorb) - CONV_PER_TAU) < 0.10,
        f"{conv/sub(P,t_q,specs.tau_absorb):.3f}")
    chk("tau model reproduces specs at the N=16 anchor",
        abs(tau_absorb_n(P, N_ANCHOR, "cint", t_q) / sub(P, t_q, specs.tau_absorb) - 1) < 0.01,
        f"{tau_absorb_n(P,N_ANCHOR,'cint',t_q)*1e9:.3f} vs "
        f"{sub(P,t_q,specs.tau_absorb)*1e9:.3f} ns")
    a, b = tile_point(P, t_q, 512, 256, 1, "cint"), tile_point(P, t_q, 4096, 256, 1, "cint")
    chk("8x N buys <1.5x TOPS at K=1 (OTA load cancels it)",
        b["tops"] / a["tops"] < 1.5, f"{b['tops']/a['tops']:.2f}x for 8x N")
    chk("conversions/MAC does fall as 1/N (law:convdens win is real)",
        abs(a["fj_per_mac_conv"] / b["fj_per_mac_conv"] - 8.0) < 0.01,
        f"{a['fj_per_mac_conv']:.2f} -> {b['fj_per_mac_conv']:.2f} fJ/MAC")

    # swing ceiling, anchor-free.
    chk("fixed-C_int swing ceiling = (MAC_MAX/CODE_MAX)^2 = 2.38x",
        abs(n_max_swing_fixed_cint() - 2.377) < 0.01,
        f"{n_max_swing_fixed_cint():.3f}x")
    # route A CSNR: -1.5 dB/octave, and the measured point allows ~1.26x.
    chk("route A costs 1.505 dB per octave of N",
        abs((csnr_n_db(P, 512, "cu") - csnr_n_db(P, 1024, "cu")) - 1.505) < 0.01,
        f"{csnr_n_db(P,512,'cu')-csnr_n_db(P,1024,'cu'):.3f} dB")
    n_a = N_PAPER * 10 ** ((CSNR_MEAS_DB - CSNR_TARGET_DB) / 5.0)
    chk("route A max N at 28.5 dB is < 1.5x", n_a / N_PAPER < 1.5,
        f"N <= {n_a:.0f} ({n_a/N_PAPER:.2f}x)")
    chk("route A max N at 34 dB is 10-20x",
        10 < (N_PAPER * 10 ** ((CSNR_HYPO_DB - CSNR_TARGET_DB) / 5.0)) / N_PAPER < 20,
        f"{10**((CSNR_HYPO_DB-CSNR_TARGET_DB)/5.0):.1f}x")

    # Q4: b_x is worth zero at K=1.
    chk("b_x 7->6 is worth EXACTLY 0 at K=1 (conversion-bound)",
        pass_time(t_q, conv, 1) == pass_time(t_q, conv, 1) and
        abs(pass_time(t_q, conv, 1) - (max(72 * t_q, conv) + 4 * t_q)) < 1e-18,
        "both = max(T_conv, .) + 4t_q")

    # Q6: CSNR reality check.
    chk("K=1 is the only K the measured CSNR supports",
        specs.parallel_k_star(CSNR_MEAS_DB, CSNR_TARGET_DB) == 1,
        f"parallel_k_star({CSNR_MEAS_DB}, {CSNR_TARGET_DB}) = "
        f"{specs.parallel_k_star(CSNR_MEAS_DB, CSNR_TARGET_DB)}")
    need9 = k_star_needed_snr(9)
    chk("window-bound (K=9) needs ~9 dB more CSNR than measured",
        8.0 < need9 - CSNR_MEAS_DB < 11.0,
        f"needs {need9:.1f} dB, have {CSNR_MEAS_DB} dB "
        f"(gap {need9-CSNR_MEAS_DB:.1f} dB)")
    tot = -10 * math.log10(10 ** (-CSNR_MEAS_DB / 10) + PELGROM_CELL["tsmc_n4_proj"] ** 2)
    chk("adding the Pelgrom floor breaks the 28 dB target at N4",
        tot < CSNR_TARGET_DB, f"{tot:.1f} dB vs {CSNR_TARGET_DB} dB target")

    # Q6(ii): batch-1 win is real and large.
    o = tile_point(P, t_q, N_PAPER, M_PAPER, 1, "cint", gm_scaled=True)
    chk("batch-1 GEMV: we beat the systolic by >3x on effective TOPS",
        o["tops"] / s["b1_tops"] > 3, f"{o['tops']/s['b1_tops']:.1f}x")
    chk("batched GEMM: we LOSE by >20x on peak TOPS",
        s["peak_tops"] / o["tops"] > 20, f"{s['peak_tops']/o['tops']:.0f}x short")

    n_fail = sum(1 for _, c, _ in ok if not c)
    print(f"\n{'PASS' if not n_fail else 'FAIL'} — {len(ok)-n_fail}/{len(ok)} checks")
    return n_fail == 0


if __name__ == "__main__":
    good = _selfcheck()
    open(OUT, "w").write(build())
    print(f"wrote {OUT}")
    sys.exit(0 if good else 1)

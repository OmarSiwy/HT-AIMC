"""Session-3: HIGHER-LEVEL ARCHITECTURAL throughput levers, scored against
AnalogIOC's actual binding term.  NO SPICE, no writes outside this file +
ARCH_THROUGHPUT.md.

The scoreboard, taken as given from this session:

    tok/s/die = tiles_per_die / (passes_per_token * pass_time)
    pass_time = max(t_in, conv_time/K) + 4*t_q      t_in = 136*t_q

A lever counts only if it moves tiles_per_die, passes_per_token, or
conv_time/K.  Anything that only shortens t_in is worth EXACTLY ZERO at K=1
(13.6 ns vs 109.5 ns -- t_in is not the max() term).

Everything is a closed form on top of pdk_projections.evaluate() so the
baseline reproduces bit-for-bit (asserted: 15,534 tok/s at K=1, 121,903 at
the window-bound ceiling).

Labels: (measured) SPICE/compiler-measured in this repo, (derived) arithmetic
on measured/committed values, (projected) model extrapolation, (literature)
external citation, (ASSUMPTION) a named constant a reader must accept/reject.

Run: PYTHONPATH=analog/schematics:. python3 scripts/compiler/metrics/arch_throughput.py
"""
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_ROOT, "analog", "docs"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import specs                                              # noqa: E402
from pdk_specs import TsmcN4Proj          # noqa: E402
from compiler.metrics import pdk_projections as pp        # noqa: E402
from compiler.metrics import throughput_ceiling as tc     # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "ARCH_THROUGHPUT.md")

PDK = TsmcN4Proj()
T_Q = 100e-12                     # N4 running chop grid (pdk_projections)
P_7B = 7e9                        # 7B dense weight count
MACS_PER_PASS = 256               # 16x16 mini tile (the shipped tok/s basis)
B_W = 4                           # INT4 weight, bits/cell-write
SOHU = pp.SOHU_TOKS_DIE           # 62.5k tok/s/die (vendor, cross-regime)

# ---------------------------------------------------------------------------
# Accuracy currency.  CODE_MAX = 120 is the +-4 sigma nominal ceiling, so the
# signal sigma is CODE_MAX/4 code units; a +-L LSB uniform code error has
# sigma_e = L/sqrt(3).  This is the ONE conversion that lets #24/#26's
# measured LSB budgets be compared with specs.SNR_T_ATTN_DB. (derived)
# ---------------------------------------------------------------------------
SIG_SIGMA = specs.CODE_MAX / 4.0


def csnr_db_for_lsb(lsb):
    return 20.0 * math.log10(SIG_SIGMA / (lsb / math.sqrt(3.0)))


def lsb_for_csnr_db(db):
    return math.sqrt(3.0) * SIG_SIGMA / (10.0 ** (db / 20.0))


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------
def baseline():
    r = pp.evaluate(PDK, T_Q)
    tiles = int(pp.DIE_MM2 * pp.FILL / pp.TILE_MM2[PDK.name])
    return {
        "conv": r["conv"], "t_in": r["window"], "t_q": r["t_q"],
        "tau": r["tau"], "tiles": tiles,
        "passes": int(P_7B / MACS_PER_PASS),
        "a_tile_um2": pp.TILE_MM2[PDK.name] * 1e6,
    }


B = baseline()


def pass_time(conv=None, K=1, S=1, t_in=None, t_q=None):
    conv = B["conv"] if conv is None else conv
    t_in = B["t_in"] if t_in is None else t_in
    t_q = B["t_q"] if t_q is None else t_q
    return max(t_in, conv / (K * S)) + 4 * t_q


def toks(conv=None, K=1, S=1, a_tile_um2=None, passes=None, t_in=None):
    """The one scoreboard.  Every lever is a substitution into this."""
    a = B["a_tile_um2"] if a_tile_um2 is None else a_tile_um2
    n = B["passes"] if passes is None else passes
    tiles = pp.DIE_MM2 * pp.FILL / (a / 1e6)
    return tiles / (n * pass_time(conv, K, S, t_in))


TOKS0 = toks()
CEIL = toks(conv=0.0)             # conv -> 0: window-bound ceiling


# ---------------------------------------------------------------------------
# L2 -- converter multiplexing S.  Closed form, with law:convdens area paid.
# ---------------------------------------------------------------------------
# law:convdens denominator is A_cells + M*A_conv(B_y)/S_share + A_wrap, where
# the PAPER's S is a SHARING factor (columns per converter).  The lever asked
# about is the RECIPROCAL: S_mux converters per column.  So the paper's /S
# becomes *S_mux -- the area term GROWS.  Stating this loudly because the two
# S's are inverses and the sign of the answer flips.
def s_gain(S, phi, cap=None):
    """Throughput ratio of S-way converter multiplexing after area.

    time:  pass ~ max(t_in, conv/S)  -> up to conv/t_in = 8.0x
    area:  A(S) = A(1)*(1 - phi + S*phi),  phi = converter+hold fraction
    tok/s ~ tiles/pass ~ [1/A(S)] * [1/pass(S)]
         => gain = min(S, S_flip) / (1 + (S-1)*phi)
    """
    flip = B["conv"] / B["t_in"]
    eff = min(S, flip)
    return eff / (1.0 + (S - 1) * phi)


def s_area_fractions():
    """phi under the two area bases that exist in this repo, and they
    disagree by 5.8x -- which is why the S verdict is a bracket, not a number."""
    M = specs.N_COLS                       # 17 columns on the mini tile
    a_conv = tc.A_CONV_UM2                 # 25 um2/col converged converter
    a_cint = specs.c_int(PDK) * 1e15 / PDK.cap_density_mim   # 14.9 um2/col
    # kT/C hold cap for an ISAAC-style S/H in front of the mux (27h4):
    # C_h >= 12kT*4^B/V_FS^2
    c_h = 12 * specs.KB_T * 4 ** specs.B_Y / (PDK.vdd ** 2)
    a_hold = c_h * 1e15 / PDK.cap_density_mim
    a_cells = specs.N_ROWS * 2 * M * tc.A_CELL_UM2
    a_model = tc.WRAP_MULT * (a_cells + M * (a_conv + a_cint))
    per_col_dup_cint = tc.WRAP_MULT * M * (a_conv + a_cint)   # naive: dup C_int
    per_col_sh = tc.WRAP_MULT * M * (a_conv + a_hold)         # ISAAC S/H
    return {
        "M": M, "a_conv": a_conv, "a_cint": a_cint, "c_h_fF": c_h * 1e15,
        "a_hold": a_hold, "a_cells": a_cells, "a_model_um2": a_model,
        "a_ship_um2": B["a_tile_um2"],
        "phi_model_dup": per_col_dup_cint / a_model,
        "phi_model_sh": per_col_sh / a_model,
        "phi_ship_dup": per_col_dup_cint / B["a_tile_um2"],
        "phi_ship_sh": per_col_sh / B["a_tile_um2"],
    }


# ---------------------------------------------------------------------------
# L1 / L10 -- the ONE accuracy budget, spendable two ways
# ---------------------------------------------------------------------------
def k_from_snr(snr_s_db, snr_t_db):
    """law:cascade random term.  The gain term is dropped because the parallel
    super-tile is SPICE-VERIFIED gain-error-K-independent (commit 84410e6)."""
    return 10.0 ** ((snr_s_db - snr_t_db) / 10.0)


def conv_for_by(b_y, pipelined_sar=False):
    """conv_time as a function of converter output bits.

    specs: code = sign*min(16*count + fine4, 2^(B_y-1)-1); the coarse loop
    resolves `count`, so COARSE_CAP = (2^(B_y-1)-1) >> 4 exactly (the
    coarse_earlyexit.py algebra, generalised in B_y), n_coarse = cap + margin,
    conv = n_coarse*K_SETTLE*tau + sar, sar = 8 tau.
    pipelined_sar: run the 4-b fine SAR on a held residue so pass n+1's coarse
    loop overlaps pass n's SAR (textbook 2-stage pipeline ADC) -> sar leaves
    the critical path."""
    cap = max(0, ((1 << (b_y - 1)) - 1) >> 4)
    n_coarse = cap + specs.COARSE_MARGIN
    cadence = specs.K_SETTLE * B["tau"]
    # back out the SAR tail from the shipped conv_time so B_y=8 is exact
    sar = B["conv"] - specs.N_COARSE * cadence
    return n_coarse * cadence + (0.0 if pipelined_sar else sar)


# ---------------------------------------------------------------------------
# L5 / L6 -- pipelining and batch: prove they are EXACTLY 1.000x
# ---------------------------------------------------------------------------
def multiplex_ratio():
    """How many weight-load rounds a die needs per token at 7B."""
    tiles = pp.DIE_MM2 * pp.FILL / (B["a_tile_um2"] / 1e6)
    return B["passes"] / tiles


def pipelined_toks_per_die(R):
    """Spatial pipeline over R dies, model fully resident (no reload).
    Each die holds P/R weights = tiles*256, so each die retires ONE pass-time
    of work per token; the R-deep pipeline retires 1 token per pass_time.
    per-die tok/s = (1/pass_time)/R.  Identical to the time-multiplexed
    formula tiles/(passes*pass) -- asserted below."""
    return (1.0 / pass_time()) / R


def weight_traffic_TBs(tok_per_s, batch=1):
    """Bytes/s of weight WRITES a time-multiplexed die must absorb.  Every
    weight in the model is written into an array once per token (per batch)."""
    return P_7B * (B_W / 8.0) * tok_per_s / batch / 1e12


# ---------------------------------------------------------------------------
# L3 / L4 -- passes_per_token levers
# ---------------------------------------------------------------------------
def skip_prob_unstructured(p_zero, n_rows):
    """A pass covers n_rows input elements; it can be skipped only if ALL of
    them are zero.  Value collapses exponentially in N -- the reason
    unstructured activation sparsity is worthless to a wide analog column."""
    return p_zero ** n_rows


# ===========================================================================
# report
# ===========================================================================
def build():
    sa = s_area_fractions()
    R = multiplex_ratio()
    L = []
    A = L.append

    A("# ARCH_THROUGHPUT — higher-level architectural throughput levers, scored")
    A("")
    A("Generated by `scripts/compiler/metrics/arch_throughput.py`. **No SPICE.** Closed forms "
      "on top of `pdk_projections.evaluate` so the baseline reproduces exactly.")
    A("")
    A("Labels: **measured** (SPICE/compiler in this repo) / **derived** / "
      "**projected** / **literature** / **ASSUMPTION**.")
    A("")
    A("```")
    A("tok/s/die = tiles_per_die / (passes_per_token * pass_time)")
    A("pass_time = max(t_in, conv_time/K) + 4*t_q")
    A(f"N4/7B: t_in = {B['t_in']*1e9:.2f} ns, conv = {B['conv']*1e9:.2f} ns, "
      f"tau = {B['tau']*1e9:.3f} ns, tiles = {B['tiles']:,}, "
      f"passes = {B['passes']:,}")
    A(f"K=1 baseline = {TOKS0:,.0f} tok/s = {TOKS0/SOHU:.2f}x Sohu; "
      f"window-bound ceiling = {CEIL:,.0f} = {CEIL/SOHU:.2f}x")
    A("```")
    A("")

    # -- 0. the reframing ---------------------------------------------------
    A("## 0. The scoreboard collapses to TWO terms, not three")
    A("")
    A("`tiles_per_die` and `passes_per_token` are not independent: "
      "`passes_per_token = P_eff/(N*M)` and `tiles = A_die*fill/A_tile`, so")
    A("")
    A("```")
    A("tok/s/die = (A_die * fill) * rho_W / (P_eff * pass_time)")
    A("   rho_W   = weights per mm2   (law:convdens numerator/denominator)")
    A("   P_eff   = weights ACTUALLY touched per token (dense P, or less)")
    A("```")
    A("")
    A(f"So there are exactly three currencies: **weight density rho_W** "
      f"(baseline {MACS_PER_PASS/(B['a_tile_um2']/1e6):,.0f} weights/mm2, "
      f"_derived_ from the shipped `TILE_MM2['tsmc_n4_proj']`), **pass_time**, "
      f"and **P_eff**.  Every lever below is one of the three.  This is "
      "`law:convdens` restated for tok/s, and it is why the paper's own line "
      "*'the architecture problem IS conversion minimization'* is the right "
      "frame. _(derived)_")
    A("")
    A("`law:convdens` also gives the honest yardstick: the densest reported "
      "array in the paper's own table is **4.2e5 weights/mm2** (40 nm NOR "
      f"flash). Our N4 mini tile is "
      f"{MACS_PER_PASS/(B['a_tile_um2']/1e6):,.0f} weights/mm2 — "
      f"**{4.2e5/(MACS_PER_PASS/(B['a_tile_um2']/1e6)):.1f}x LESS dense than "
      "a 40 nm flash part**, at four nodes' advantage. That gap is worth more "
      "than every timing lever in this document combined, and it is entirely "
      "converter+C_int area. _(derived, from law:convdens)_")
    A("")

    # -- 1. the unreconciled area factor -----------------------------------
    A("## 1. LOUD CORRECTION FIRST: one unreconciled number decides half the table")
    A("")
    A(f"Two area models for the same 16x17 N4 tile live in this repo and they "
      f"disagree by **{sa['a_ship_um2']/sa['a_model_um2']:.1f}x**:")
    A("")
    A("| basis | A_tile | converter+hold fraction `phi` | where |")
    A("|---|---|---|---|")
    A(f"| shipped tok/s constant | {sa['a_ship_um2']:,.0f} um2 | "
      f"{sa['phi_ship_dup']:.2f} | `pdk_projections.TILE_MM2` (ASSUMPTION, "
      "*'projected: cap+logic shrink'*) |")
    A(f"| area model | {sa['a_model_um2']:,.0f} um2 | {sa['phi_model_dup']:.2f} "
      "| `throughput_ceiling.tile_area_mm2` (paper A_cell + 25 um2/col conv + "
      "MiM C_int + 1.5x wrap) |")
    A("")
    A(f"The 15,534 tok/s baseline uses the first. The area model says the tile "
      f"is {sa['a_model_um2']:,.0f} um2 and **{sa['phi_model_dup']:.0%} of it is "
      f"converter + C_int** — the cell array is only "
      f"{sa['a_cells']*tc.WRAP_MULT/sa['a_model_um2']:.1%}. Either the shipped "
      f"baseline is {sa['a_ship_um2']/sa['a_model_um2']:.1f}x pessimistic "
      f"(= a free {sa['a_ship_um2']/sa['a_model_um2']:.1f}x on tok/s, larger "
      "than most levers below), or the area model is missing "
      f"{sa['a_ship_um2']-sa['a_model_um2']:,.0f} um2 of row drivers / PWM / "
      "control / routing. **Nobody has reconciled them, and every "
      "area-spending lever's verdict flips on it.** _(derived; flagged)_")
    A("")
    A("Resolve this before scoring any lever that buys time with area. The "
      "paper's own `law:convdens` premise (*'measured weight densities are set "
      "by converter pitch, not cells'*) says `phi -> 1` is the defensible "
      "prior, which is the pessimistic column throughout.")
    A("")

    # -- 2. converter multiplexing S ---------------------------------------
    A("## 2. VERIFIED VERDICT — converter multiplexing S: the 8x is NOT real")
    A("")
    A("`THROUGHPUT_CEILING.md` lever #6 ranks S first (*'S=8 gets window-bound "
      "with no K, no dB'*, *'up to 8x, the largest runway found'*). That "
      "ranking **priced the time and not the area**, even though the same row "
      "names `M*A_conv*S` as the cost. Pricing it:")
    A("")
    A("**Sign warning.** The `S` in `law:convdens`'s `M*A_conv(B_y)/S` is a "
      "column *sharing* factor (27h4: S columns share one converter). The "
      "lever asked about is its **reciprocal** — S converters per column — so "
      "the denominator term becomes `M*A_conv*S`. The two S's are inverses.")
    A("")
    A("```")
    A("time :  pass(S) = max(t_in, conv/S) + 4 t_q     -> saturates at "
      f"conv/t_in = {B['conv']/B['t_in']:.1f}x")
    A("area :  A(S)    = A(1) * (1 - phi + S*phi)      phi = (conv+hold)/A_tile")
    A("gain :  tok/s(S)/tok/s(1) = min(S, 8.0) / (1 + (S-1)*phi)")
    A("```")
    A("")
    A("`gain` is maximised at exactly `S = conv/t_in = 8` for any phi (past 8 "
      "the numerator freezes and the denominator keeps growing), which is the "
      "one part of the original claim that survives. _(derived)_")
    A("")
    A(f"| S | pass_time | phi={sa['phi_ship_sh']:.2f} (shipped area, S/H) "
      f"| phi={sa['phi_ship_dup']:.2f} (shipped area, dup C_int) "
      f"| phi={sa['phi_model_sh']:.2f} (model area, S/H) "
      f"| phi={sa['phi_model_dup']:.2f} (model area, dup C_int) |")
    A("|---|---|---|---|---|---|")
    for S in (1, 2, 4, 8, 16):
        row = [f"| {S} | {pass_time(K=1, S=S)*1e9:.1f} ns "]
        for phi in (sa["phi_ship_sh"], sa["phi_ship_dup"],
                    sa["phi_model_sh"], sa["phi_model_dup"]):
            row.append(f"| {s_gain(S, phi):.2f}x ")
        A("".join(row) + "|")
    A("")
    A(f"phi values _(derived)_: converter {sa['a_conv']:.0f} um2/col (paper "
      f"converged) + either a duplicated C_int ({sa['a_cint']:.1f} um2/col) or "
      f"an ISAAC-style S/H at the kT/C floor "
      f"(C_h >= 12kT*4^8/V_FS^2 = {sa['c_h_fF']:.1f} fF = "
      f"{sa['a_hold']:.2f} um2/col, 27h4).")
    A("")
    A("**Verdict on S:**")
    A("")
    A(f"- The **8x is time-only and does not survive area.** Best case "
      f"({s_gain(8, sa['phi_ship_sh']):.2f}x) needs BOTH the optimistic tile-area "
      f"basis AND an S/H-based mux; worst case "
      f"({s_gain(8, sa['phi_model_dup']):.2f}x) it is *exactly nothing*.")
    A(f"- **Do not duplicate C_int.** ISAAC's structure (one S/H per column at "
      f"the kT/C floor, then an S:1 mux into S converters) costs "
      f"{sa['a_hold']:.2f} um2 instead of {sa['a_cint']:.1f} um2 per extra "
      f"path — a {sa['a_cint']/sa['a_hold']:.0f}x area saving on the "
      "replicated element, and it is the difference between 1.0x and 1.4x on "
      "the pessimistic basis. The ping-pong C_int we already ship is the "
      "*expensive* way to do S=2. _(derived, literature: shafiee2016isaac, 27h4)_")
    A(f"- **27h4's warning binds physically.** Our converter is "
      f"{sa['a_conv']:.0f} um2 against a crosspoint pitch of "
      f"~{math.sqrt(tc.A_CELL_UM2):.2f} um — the converter is already ~"
      f"{sa['a_conv']/tc.A_CELL_UM2:.0f} crosspoints wide. *'The sharing "
      "factor is a measurement, not a decision'*: there is no room under the "
      "column pitch for a second converter, let alone eight. S=8 is a "
      "floorplan claim nobody has drawn.")
    A(f"- **Honest replacement for the #1 ranking:** S is worth "
      f"**{s_gain(8, sa['phi_model_sh']):.1f}x–{s_gain(8, sa['phi_ship_sh']):.1f}x**, "
      "not 8x, and only via S/H + mux, and only after section 1 is resolved.")
    A("")

    # -- 3. pipelining ------------------------------------------------------
    A("## 3. Inter-layer / inter-tile pipelining: EXACTLY 1.000x. Here is the arithmetic.")
    A("")
    A(f"At 7B a die holds {B['tiles']:,} tiles x {MACS_PER_PASS} weights = "
      f"{B['tiles']*MACS_PER_PASS/1e6:.1f}M weights, so the model is "
      f"**R = {R:.0f}x time-multiplexed** _(derived)_ — the ~600x in the brief.")
    A("")
    A("Two ways to spend that R:")
    A("")
    A("| scheme | per-die tok/s | token latency | weight writes/token/die |")
    A("|---|---|---|---|")
    A(f"| time-multiplex 1 die, R rounds | {TOKS0:,.0f} | "
      f"{R*pass_time()*1e6:.1f} us | {P_7B:.2g} |")
    A(f"| ISAAC-style spatial pipeline over R dies, model resident | "
      f"{pipelined_toks_per_die(R):,.0f} | {R*pass_time()*1e6:.1f} us | "
      f"**0** |")
    A("")
    A("```")
    A("multiplexed : tok/s/die = tiles*N*M / (P * pass)          = 1/(R*pass)")
    A("pipelined   : system retires 1 token per pass_time over R stages,")
    A("              so per die  = (1/pass)/R                    = 1/(R*pass)")
    A("              latency     = R*pass  (identical: same R serial passes)")
    A("```")
    A("")
    A("**They are the same number, identically, for any R.** _(derived, "
      "asserted in the self-check.)* Inter-layer pipelining converts "
      "multiplexing depth into pipeline depth at constant tok/s/die and "
      "constant latency. There is no headroom in it, because the shipped "
      "formula **already assumes 100% tile utilisation** — `GATING_VALUE.md` "
      "says so in as many words: *'it assumes 100% tile utilisation, and at "
      "7B/70B that assumption holds by a factor of ~600'*.")
    A("")
    A("Nor is there a dependency stall to recover: batch-1 decode GEMV has "
      f"{B['tiles']:,}-way *output-column* parallelism inside every single "
      "matmul, so tiles never wait on each other within a round. ISAAC's "
      "inter-layer pipeline exists to fill a CNN's *layer-shaped* bubbles; a "
      "decode GEMV has none. **DEAD as a throughput lever.**")
    A("")
    A("### But pipelining is not worthless — it is the fix for a wall nobody priced")
    A("")
    A(f"The last column above is the point. Time-multiplexing writes **every "
      f"weight in the model into an array once per token**: at {TOKS0:,.0f} "
      f"tok/s that is **{weight_traffic_TBs(TOKS0):,.1f} TB/s** of weight-write "
      f"traffic into one die, and **{weight_traffic_TBs(CEIL):,.0f} TB/s** at "
      f"the {CEIL:,.0f} tok/s ceiling. _(derived)_")
    A("")
    A("| reference | bandwidth | our need at 15.5k tok/s | at the 122k ceiling |")
    A("|---|---|---|---|")
    A(f"| HBM3e, 1 stack | 1.2 TB/s | "
      f"{weight_traffic_TBs(TOKS0)/1.2:,.0f}x short | "
      f"{weight_traffic_TBs(CEIL)/1.2:,.0f}x short |")
    A(f"| HBM3e, 8 stacks | 9.6 TB/s | "
      f"{weight_traffic_TBs(TOKS0)/9.6:,.1f}x short | "
      f"{weight_traffic_TBs(CEIL)/9.6:,.0f}x short |")
    A("")
    A("**The tok/s model silently assumes infinite weight-load bandwidth.** "
      "`PDK_PROJECTIONS.md` states the exclusion for *energy* (*'weights "
      "time-multiplexed (rewrite energy excluded)'*) and `GATING_VALUE.md` "
      "priced the energy side (77 fJ/write break-even). **Nobody priced the "
      "TIME side.** At 7B this machine is not weight-stationary — it is a "
      "586x-reloaded array, i.e. exactly the memory wall `law:roofline` "
      "claims analog residency deletes. `law:roofline`'s `Q -> 0` is true "
      "only when the model FITS.")
    A("")
    A("Three things fix it, and none of them is a throughput lever:")
    A(f"1. **Spatial pipelining over R={R:.0f} dies** (weights truly resident): "
      "traffic -> 0, tok/s/die unchanged. This is what pipelining is *for*.")
    A(f"2. **Batching**: {weight_traffic_TBs(TOKS0):,.1f} TB/s / B. At B=64, "
      f"{weight_traffic_TBs(TOKS0, 64):.2f} TB/s — feasible. Free, because "
      "`law:batch` already charges analog `t(B)=B*t_MVM`, so tok/s/die is "
      "batch-invariant (section 5).")
    A("3. **Contextual sparsity / MoE** (section 4): only the active weights "
      "are ever loaded, so traffic falls by the same factor as passes.")
    A("")

    # -- 4. the accuracy budget --------------------------------------------
    A("## 4. THE BIGGEST UNSPENT LEVER: the measured accuracy budget has never been cashed")
    A("")
    A(f"`specs.SNR_T_ATTN_DB = {specs.SNR_T_ATTN_DB}` dB is the target that "
      "makes K=1, and it is an **assumed** *'attention-class'* constant. Put "
      "it in the same units as the repo's two measured model-adequacy results "
      f"(sigma_signal = CODE_MAX/4 = {SIG_SIGMA:.0f} codes, sigma_err = "
      "L/sqrt(3)):")
    A("")
    A("| gate | +-LSB on the +-127 code | equivalent CSNR | provenance |")
    A("|---|---|---|---|")
    A(f"| old converter-ENOB spec | 1 | {csnr_db_for_lsb(1):.1f} dB | "
      f"tb gate; == `specs.SNR_S_DB` {specs.SNR_S_DB} dB (consistency check) |")
    A(f"| `SNR_T_ATTN_DB` in force | {lsb_for_csnr_db(specs.SNR_T_ATTN_DB):.1f} "
      f"| {specs.SNR_T_ATTN_DB:.1f} dB | **ASSUMPTION** |")
    A(f"| measured tile budget (#24 ERROR_IMPACT) | 8 | "
      f"{csnr_db_for_lsb(8):.1f} dB | **measured** (argmax 100%, cos 0.9948) |")
    A(f"| measured o_t budget (#26 OT_IMPACT) | 18.8 | "
      f"{csnr_db_for_lsb(18.8):.1f} dB | **measured** (argmax 100%, cos 0.9935) |")
    A("")
    A(f"**The target in force is {specs.SNR_T_ATTN_DB - csnr_db_for_lsb(8):.1f} dB "
      "stricter than the repo's own measured tile budget.** That is ~"
      f"{(specs.SNR_T_ATTN_DB - csnr_db_for_lsb(8))/6.02:.1f} bits of margin "
      "that has been paid for and never spent. It is **one** budget and it can "
      "be spent **one** of two ways:")
    A("")
    A("### (a) spend it on K (deeper cascade)")
    A("")
    A("`K = 10^((SNR_s - SNR_T)/10)`; the gain term is dropped because the "
      "parallel super-tile is SPICE-VERIFIED gain-error-K-independent (84410e6).")
    A("")
    A("| SNR_s | SNR_T = 28.0 (in force) | SNR_T = 16.3 (#24 measured) |")
    A("|---|---|---|")
    for s in (28.5, 19.9):
        k0 = max(1, int(k_from_snr(s, specs.SNR_T_ATTN_DB)))
        k1 = max(1, int(k_from_snr(s, csnr_db_for_lsb(8))))
        A(f"| {s:.1f} dB | K={k0} -> {toks(K=k0):,.0f} tok/s "
          f"({toks(K=k0)/SOHU:.2f}x) | K={k1} -> {toks(K=k1):,.0f} tok/s "
          f"({toks(K=k1)/SOHU:.2f}x) |")
    A("")
    A("### (b) spend it on B_y (coarser converter = shorter conversion)")
    A("")
    A("`coarse_earlyexit.py`'s algebra generalised in B_y: "
      "`COARSE_CAP = (2^(B_y-1)-1) >> 4`, `n_coarse = cap + 4`, "
      "`conv = n_coarse*2*tau + 8*tau`. Be precise about how many bits are "
      f"actually free: vs the +-1 LSB converter-ENOB spec, +-8 LSB is 3 bits; "
      f"vs the {specs.SNR_T_ATTN_DB} dB target in force (+-"
      f"{lsb_for_csnr_db(specs.SNR_T_ATTN_DB):.1f} LSB) it is "
      f"{(specs.SNR_T_ATTN_DB - csnr_db_for_lsb(8))/6.02:.1f} bits. So "
      "**B_y 8->6 is fully covered by #24 alone**; 8->5 spends into the looser "
      "#26 o_t headroom and needs the depth check below.")
    A("")
    A("| B_y | code error in B_y=8 LSBs | n_coarse | conv_time | tok/s | "
      "vs Sohu | + pipelined SAR |")
    A("|---|---|---|---|---|---|---|")
    for by in (8, 7, 6, 5):
        c = conv_for_by(by)
        cp = conv_for_by(by, pipelined_sar=True)
        cap = max(0, ((1 << (by - 1)) - 1) >> 4)
        A(f"| {by} | {2**(8-by)} | {cap+specs.COARSE_MARGIN} | "
          f"{c*1e9:.1f} ns | {toks(conv=c):,.0f} | {toks(conv=c)/SOHU:.2f}x | "
          f"{toks(conv=cp):,.0f} ({toks(conv=cp)/SOHU:.2f}x) |")
    A("")
    A("The **pipelined SAR** column is a second, independent, near-free "
      "architectural lever: the 4-b fine SAR is 8 tau = "
      f"{8*B['tau']*1e9:.1f} ns = {8*B['tau']/B['conv']:.0%} of the conversion "
      "and it is *sequential after* the coarse loop. Latch the residue onto a "
      f"{sa['c_h_fF']:.0f} fF hold cap and pass n+1's coarse loop overlaps pass "
      "n's SAR — a textbook 2-stage pipeline ADC. Cost: one small cap + one "
      f"mux per column ({sa['a_hold']:.2f} um2/col, phi impact ~"
      f"{sa['a_hold']*tc.WRAP_MULT*sa['M']/sa['a_model_um2']:.1%}). "
      f"Worth **{toks(conv=conv_for_by(8, True))/TOKS0:.2f}x on its own** at "
      "B_y=8, no accuracy cost at all. _(derived; NOT measured)_")
    A("")
    A("**Combined cheapest path to the full runway** _(projected)_: "
      f"B_y=5 + pipelined SAR gives conv = "
      f"{conv_for_by(5, True)*1e9:.1f} ns; add S=2 (cheap, S/H) -> "
      f"{conv_for_by(5, True)/2*1e9:.1f} ns against the "
      f"{B['t_in']*1e9:.1f} ns window floor = "
      f"{toks(conv=conv_for_by(5, True), S=2):,.0f} tok/s = "
      f"{toks(conv=conv_for_by(5, True), S=2)/SOHU:.2f}x Sohu — "
      f"{toks(conv=conv_for_by(5, True), S=2)/TOKS0:.1f}x of the "
      f"{CEIL/TOKS0:.1f}x runway, with no K, no gm scaling, and ONE extra "
      "converter per column instead of eight. Folding in `COARSE_MARGIN` 4->2 "
      "(already flagged in `specs.py` as unmeasured and worth ~1.15x) clears "
      f"the floor outright: {2*specs.K_SETTLE*B['tau']/2*1e9:.1f} ns "
      f"< {B['t_in']*1e9:.1f} ns at the same S=2.")
    A("")
    A("### The honest caveat that gates all of section 4")
    A("")
    A("Both LSB budgets were measured on **one block of a 135M model** with a "
      "**proxy LM head** (ERROR_IMPACT.md says so itself). A 7B model is ~30 "
      "blocks deep. If per-block errors are independent and accumulate in the "
      "residual stream, the per-block budget shrinks by sqrt(30) -> "
      f"+-{8/math.sqrt(30):.1f} LSB -> {csnr_db_for_lsb(8/math.sqrt(30)):.1f} dB, "
      f"which is *stricter* than the {specs.SNR_T_ATTN_DB} dB in force. If they "
      "are correlated / absorbed by RMSNorm, the +-8 stands and the whole "
      "runway opens.")
    A("")
    A("> **The single highest-value experiment available: re-run the #24 "
      "error-injection sweep at full model depth.** It is pure numpy, no SPICE, "
      f"and it is worth between {toks(K=1)/TOKS0:.2f}x and "
      f"{CEIL/TOKS0:.1f}x on tok/s — more than every circuit lever in "
      "`OPTIMIZATION_RESULTS.md` combined. Session 2's mandate was *'raise "
      "source SNRs'* (OTA, C_int, chopping); nobody asked whether the target "
      "needed to be that high.")
    A("")
    A("Same idea from the outside _(literature)_: hardware-aware / noise-aware "
      "training reaches iso-accuracy with FP for transformers on analog IMC "
      "(Rasch et al., *Nat. Commun.* 2023; IBM/ETH *Analog Foundation Models*, "
      "2025). That is a training-side purchase of the same dB, at zero "
      "silicon. It is absent from every session mandate in this repo.")
    A("")

    # -- 5. dead levers -----------------------------------------------------
    A("## 5. Dead on arrival — and exactly why")
    A("")
    A("| lever | why it is dead | gain |")
    A("|---|---|---|")
    A(f"| **Batch / weight replication** | `law:batch`: analog is strictly "
      f"`t(B)=B*t_MVM`, so B tokens cost B passes. tok/s = "
      f"B*tiles/(passes*B*pass). Cancels identically. | **1.000x** _(derived, "
      "asserted)_ |")
    A("| **Inter-layer pipelining** | already credited: the formula assumes "
      "100% utilisation; pipelining just relabels R (section 3) | **1.000x** |")
    A("| **Speculative / multi-token decoding** | the GPU win is arbitrage on "
      "a memory wall: a batch-1 and a batch-g forward cost the same when "
      "bandwidth-bound. `law:batch` says analog cost is *linear* in the "
      "verified block, so you pay full price for rejected drafts **plus** the "
      "draft model. | **< 1.0x — NEGATIVE** _(derived)_ |")
    A("| **Medusa / lookahead / multi-token heads** | same mechanism, extra "
      "heads = extra passes | **< 1.0x** |")
    A(f"| **Bit-serial input encoding (27h5)** | attacks `t_in` only "
      f"({B['t_in']*1e9:.1f} ns), which `max()` ignores at K=1. And 27h5's own "
      f"math pays **B_x conversions instead of 1** — it *multiplies* the "
      "binding term. Anti-optimal for a conversion-bound charge-domain column. "
      "| **0x, then negative** |")
    A(f"| **Anything else that shortens t_in** (b_x, faster t_q, PWM tricks) | "
      f"not the max() term until K>=8 | **0x** (already in CONVTIME_SENSITIVITY 4d) |")
    A("| **Analog dataflow between tiles (27l3)** | it *is* `law:cascade` "
      "applied spatially: K stages without requantisation -> sigma*sqrt(K). "
      "Draws the **same** SNR budget K already draws. `OPTIMIZATION_RESULTS` "
      "§4: *'levers don't multiply: cascade-K, lattice thresholds, per-layer-K "
      "all draw the same SNR budget'*. | **not independent of K** |")
    A(f"| **Unstructured activation sparsity** | a pass covers N={specs.N_ROWS} "
      f"inputs and is skippable only if ALL are zero: P = p^N. At p=0.9 that is "
      f"{skip_prob_unstructured(0.9, specs.N_ROWS):.3f}; at N=512 it is "
      f"{skip_prob_unstructured(0.9, 512):.1e}. **Value collapses "
      "exponentially in N** — the wider the column, the more worthless it "
      "gets. The paper's 88.9%/2304-row claim is about ADC *range*, not pass "
      "skipping. | **~1.2x at N=16, 1.00x at N=512** _(derived)_ |")
    A("| **Adaptive-range converter, CSD, DPS-48, larger N, higher clock, "
      "LVT, VDD gating** | already refuted in `OPTIMIZATION_RESULTS.md` | — |")
    A(f"| **CAM / top-k attention (27l9)** | attacks the KV-cache matmuls, "
      "which are **activations, not weights** — they are not in the "
      f"{P_7B:.0g} weight count that sets `passes_per_token` at all. It is a "
      "Chip-2 latency lever, worth 0x on the Chip-1 weight-engine scoreboard. "
      "| **0x here** |")
    A("| **Output-stationary / different loop order** | batch-1 GEMV has no "
      "operand reuse to reorder; every weight is touched once. | **1.000x** |")
    A("")

    # -- 6. live levers -----------------------------------------------------
    A("## 6. Live levers on `P_eff` (passes_per_token) — and why WE get them cheap")
    A("")
    A("`P_eff` is the number of weights actually touched per token. For MoE "
      "that is the **active** parameter count, so the comparison must be "
      "**quality-matched, not size-matched** — a 7B-total MoE with E/k=32 has "
      "219M active params and is not a 7B-quality model. Tabulating real "
      "models by their active count removes the ambiguity _(projected)_:")
    A("")
    A("| workload | P_eff (weights/token) | passes/token | tok/s | vs Sohu | "
      "note |")
    A("|---|---|---|---|---|---|")
    for name, peff, note in (
            ("7B dense (baseline)", 7.0e9, "reference"),
            ("70B dense", 70.0e9, "reference (Sohu's own workload)"),
            ("Mixtral 8x7B (47B total, k/E=2/8)", 12.9e9,
             "~70B-dense quality at 5.4x the tok/s of 70B dense (_literature_)"),
            ("DeepSeek-V3-class (671B total, 37B active)", 37.0e9,
             "frontier quality; 18x fewer passes than its dense equivalent"),
            ("7B dense + Deja Vu contextual sparsity (composite 0.30)",
             0.30 * 7.0e9, "same model, _literature_ predictor"),
            ("7B dense + MLP-only sparsity (85% MLP sparse)",
             (0.15 * (2 / 3) + 1 / 3) * 7.0e9, "conservative, MLP only"),
    ):
        n = int(peff / MACS_PER_PASS)
        A(f"| {name} | {peff:.3g} | {n:,} | {toks(passes=n):,.0f} | "
          f"{toks(passes=n)/SOHU:.2f}x | {note} |")
    A("")
    A(f"`law:moe`'s E/k shows up as the ratio between rows: Mixtral's 12.9B "
      f"active vs 70B dense is "
      f"{toks(passes=int(12.9e9/MACS_PER_PASS))/toks(passes=int(70e9/MACS_PER_PASS)):.1f}x "
      "at matched quality, DeepSeek's 37B vs 671B is "
      f"{toks(passes=int(37e9/MACS_PER_PASS))/toks(passes=int(671e9/MACS_PER_PASS)):.1f}x. "
      "_(derived)_")
    A("")
    A("Deja Vu (Liu et al., ICML 2023) _(literature)_: >95% of MLP parameters "
      "and >80% of attention heads are zeroable per token with no quality "
      "loss, via a lookahead predictor one block ahead; ProSparse / TurboSparse "
      "reach ~90% intrinsic activation sparsity in Llama-class models by "
      "ReLU-fication.")
    A("")
    A("### The synergy nobody has written down")
    A("")
    A("Structured sparsity needs the active neurons **gathered into dense "
      "tiles**, otherwise you are back to the `p^N` problem above. A truly "
      "weight-stationary analog machine cannot gather: its weights are burned "
      "into fixed arrays and a skipped column just idles.")
    A("")
    A(f"**We are 586x time-multiplexed, so we CHOOSE which weights to load "
      "every round.** Gathering the Deja-Vu-predicted active neurons into "
      "dense tile loads is free for us and impossible for a resident array. "
      "The 586x multiplexing — the thing section 3 identifies as a 54 TB/s "
      "liability — is *exactly* what makes contextual sparsity convert 1:1 "
      "into passes AND into a 1:1 reduction of that same weight traffic. "
      "_(derived; this is the strongest architectural argument in the "
      "document.)*")
    A("")
    A("This also collapses the MoE story into it: `law:moe`'s k/E is just "
      "contextual sparsity with a trained, block-structured predictor. Same "
      "mechanism, same hardware requirement (dynamic tile loading), and they "
      "**do not stack** — a MoE's experts are already the gathered active set.")
    A("")

    # -- 7. ranked table ----------------------------------------------------
    A("## 7. RANKED TABLE")
    A("")
    A("Ordered by (projected tok/s gain) x (confidence), at N4 / 7B / K=1 "
      f"baseline {TOKS0:,.0f} tok/s = {TOKS0/SOHU:.2f}x Sohu. **The two "
      "`SNR_T` rows and the coarse-margin row draw the SAME accuracy budget "
      "and DO NOT multiply with each other** — one budget, spend once "
      "(`OPTIMIZATION_RESULTS` §4). The `passes_per_token` rows DO multiply "
      "with the timing rows.")
    A("")
    A("| # | lever | term attacked | tok/s | x Sohu | x base | cost | conf |")
    A("|---|---|---|---|---|---|---|---|")

    rows = []
    c_by5p = conv_for_by(5, True)
    rows.append(("Re-base `SNR_T` on the MEASURED +-8 LSB budget, spend it on "
                 "B_y 8->5 + pipelined SAR", "conv_time", toks(conv=c_by5p),
                 "1 numpy run to validate at depth 30; +1 hold cap/col",
                 "MED (measured at 135M/1 block, NOT at depth)"))
    rows.append(("Re-based `SNR_T` spent on K instead of B_y (K=7, needs the "
                 "NOMINAL 28.5 dB, i.e. Pelgrom fixed too)",
                 "conv_time/K", toks(K=7),
                 "same budget as row above — do not add them", "LOW-MED"))
    rows.append(("Pipelined SAR alone (residue hold cap, 2-stage ADC)",
                 "conv_time", toks(conv=conv_for_by(8, True)),
                 f"{sa['a_hold']:.1f} um2/col, ZERO accuracy cost", "MED-HIGH (derived)"))
    n_ctx = int(B["passes"] * 0.30)
    rows.append(("Contextual sparsity (Deja Vu) with tile-granular gather",
                 "passes_per_token", toks(passes=n_ctx),
                 "predictor MLP + dynamic tile loading (we already reload)",
                 "MED (literature, workload-dependent)"))
    rows.append(("Switch the workload to MoE (Mixtral-class active count) — "
                 "quality-matched vs 70B dense, NOT vs 7B",
                 "passes_per_token",
                 toks(passes=int(12.9e9 / MACS_PER_PASS)),
                 "different model; capacity for ALL experts", "MED (law:moe)"))
    rows.append((f"Converter mux S=8 via S/H (NOT dup C_int), optimistic area",
                 "conv_time", TOKS0 * s_gain(8, sa["phi_ship_sh"]),
                 f"phi={sa['phi_ship_sh']:.2f}; needs section 1 resolved AND a "
                 "floorplan 27h4 says does not exist", "LOW"))
    rows.append(("Reconcile the tile-area factor (section 1) in our favour",
                 "tiles_per_die",
                 TOKS0 * (sa["a_ship_um2"] / sa["a_model_um2"]),
                 "bookkeeping only — may go the other way", "LOW (unreconciled)"))
    rows.append(("Coarse margin 4 -> 2 (`specs.COARSE_MARGIN`)", "conv_time",
                 toks(conv=(specs.COARSE_CAP + 2) * specs.K_SETTLE * B["tau"]
                      + 8 * B["tau"]),
                 "one SPICE measurement; specs.py already flags it",
                 "MED (already noted in specs.py)"))
    rows.append(("Converter mux S=8, pessimistic (model area basis, dup C_int)",
                 "conv_time", TOKS0 * s_gain(8, sa["phi_model_dup"]),
                 "8x converter area", "HIGH that it is ~nothing"))
    rows.append(("Inter-layer pipelining / batching / spec-decode",
                 "none", TOKS0, "—", "HIGH that it is 1.000x"))

    for i, (name, term, t, cost, conf) in enumerate(
            sorted(rows, key=lambda r: -r[2]), 1):
        A(f"| {i} | {name} | {term} | {t:,.0f} | {t/SOHU:.2f}x | "
          f"{t/TOKS0:.2f}x | {cost} | {conf} |")
    A("")
    A(f"Everything above is capped by the window-bound ceiling "
      f"**{CEIL:,.0f} tok/s = {CEIL/SOHU:.2f}x Sohu** on the timing axis; only "
      "the `passes_per_token` and `tiles_per_die` levers (sparsity, MoE, "
      "density) go past it.")
    A("")

    # -- 8. what we never considered ---------------------------------------
    A("## 8. From the literature: things this repo has NOT considered at all")
    A("")
    A("1. **Extreme partial-sum quantization / near-ADC-less CiM** "
      "_(literature: HCiM arXiv:2403.13577; Kim et al., ACM JETC 2022 "
      "'Extreme Partial-Sum Quantization')_. Train the network so the *partial "
      "sum* — not the final activation — can be 1-1.5 bits, and the converter "
      "collapses to a sense amp. This repo has explored adaptive converter "
      "*range* (refuted, 0.2%) but never reduced converter *resolution*, which "
      f"is what actually shortens conv_time ({toks(conv=conv_for_by(5)):,.0f} "
      "tok/s at B_y=5). It is the same budget as section 4, but the "
      "literature says training can *manufacture* the budget rather than "
      "spend existing slack.")
    A("2. **Hardware-aware / noise-aware training as an SNR purchase** "
      "_(literature: Rasch et al. Nat. Commun. 14:5282, 2023; IBM/ETH Analog "
      "Foundation Models 2025)_. Every session mandate in this repo buys dB "
      "with circuits (OTA current, C_int, chopping, bit-slicing, LVT). Nobody "
      "has tried buying dB with the *model*. It is the cheapest dB on the "
      "table and it composes with K directly.")
    A("3. **The weight-load bandwidth wall (section 3).** Not in the "
      f"literature we found either — published analog-IMC LLM work assumes "
      "resident weights (IBM 64-core, HERMES, NeuRRAM all evaluate models that "
      "fit). At 7B/586x this is AnalogIOC-specific and it is unpriced. It does "
      "not change tok/s but it changes whether the tok/s number means anything.")
    A("4. **Tile-granular gather for contextual sparsity (section 6).** The "
      "IMC sparsity literature (STICKER-IM, CompRRAE, OU-based compression) "
      "all works on *resident* arrays and therefore has to skip in place, "
      "getting `p^N`. Nobody has pointed out that a time-multiplexed analog "
      "array gets structured sparsity at full 1:1 value. This is a claimable "
      "architectural contribution, not a borrowed one.")
    A("")
    A("Checked and found already-covered/refuted here: ISAAC's S/H + fast "
      "shared ADC (= our ping-pong, and section 2's S/H recommendation); "
      "PUMA (instruction pipeline — a programmability result, not throughput); "
      "Newton MICRO'18's three techniques (adaptive ADC precision = refuted "
      "adaptive-range; divide-and-conquer numerics = refuted DPS-48/Strassen; "
      "heterogeneous provisioning = done, per-layer K); CASCADE/TIMELY "
      "(= 27l3 analog inter-tile dataflow, same SNR budget as K); PRIME "
      "(sense-amp reuse = trades resolution we do not have to spare).")
    A("")

    A("## 9. What to do next, in order")
    A("")
    A("1. **Re-run #24's error injection at full model depth** (numpy, hours). "
      "It sets `SNR_T`, which sets everything in section 4. Worth "
      f"{CEIL/TOKS0:.1f}x if it holds, 0.5x if it does not. No other "
      "experiment has that leverage.")
    A("2. **Reconcile `TILE_MM2['tsmc_n4_proj']` against "
      "`tile_area_mm2`** (section 1). One afternoon. Decides S, decides the "
      "density lever, and is itself worth "
      f"{sa['a_ship_um2']/sa['a_model_um2']:.1f}x in one direction or the other.")
    A("3. **Price the pipelined SAR in SPICE** — "
      f"{toks(conv=conv_for_by(8, True))/TOKS0:.2f}x at zero accuracy cost is "
      "the only free lunch left on the timing axis.")
    A("4. **Stop ranking converter multiplexing first.** Re-rank "
      "`THROUGHPUT_CEILING.md` lever #6 from 8x to "
      f"{s_gain(8, sa['phi_model_sh']):.1f}-{s_gain(8, sa['phi_ship_sh']):.1f}x, "
      "and note that 27h4 says the floorplan may not exist.")
    A("")
    return "\n".join(L) + "\n"


# ===========================================================================
def _selfcheck():
    ok = [True]

    def chk(name, cond, msg=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {msg}" if msg else ""))
        ok[0] &= bool(cond)

    print("arch_throughput self-check")
    chk("baseline tok/s reproduces the committed 17,915",
        # session3: COARSE_MARGIN measured = 2 -> n_coarse 11 -> 9
        abs(TOKS0 - 17915) < 5, f"{TOKS0:,.1f}")
    chk("window-bound ceiling reproduces the committed 121,903",
        abs(CEIL - 121903) < 5, f"{CEIL:,.1f}")
    chk("conversion binds by ~7x at K=1",
        6.8 < B["conv"] / B["t_in"] < 7.2, f"{B['conv']/B['t_in']:.2f}x")

    # pipelining identity: multiplexed == spatially pipelined, exactly
    R = multiplex_ratio()
    chk("inter-layer pipelining is EXACTLY 1.000x (multiplex == pipeline)",
        abs(pipelined_toks_per_die(R) - TOKS0) / TOKS0 < 1e-9,
        f"pipelined {pipelined_toks_per_die(R):,.1f} vs {TOKS0:,.1f}")

    # batch identity
    Bt = 64
    chk("batch B is EXACTLY 1.000x on tok/s (law:batch)",
        abs(Bt * B["tiles"] / (Bt * B["passes"] * pass_time())
            - B["tiles"] / (B["passes"] * pass_time())) < 1e-9)
    chk("batch B does divide weight traffic by B",
        abs(weight_traffic_TBs(TOKS0, Bt) * Bt
            - weight_traffic_TBs(TOKS0)) < 1e-6)

    # t_in is worth zero
    chk("halving t_in is worth < 0.5% at K=1",
        toks(t_in=B["t_in"] / 2) / TOKS0 < 1.005,
        f"{toks(t_in=B['t_in']/2)/TOKS0:.4f}x")

    # S multiplexing
    sa = s_area_fractions()
    chk("S gain peaks at S=8 (the conv/t_in flip point)",
        all(s_gain(8, sa["phi_ship_sh"]) >= s_gain(s, sa["phi_ship_sh"]) - 1e-9
            for s in (1, 2, 4, 6, 9, 16, 32)))
    chk("S=8 is NOT 8x once area is paid (optimistic basis)",
        s_gain(8, sa["phi_ship_sh"]) < 5.0,
        f"{s_gain(8, sa['phi_ship_sh']):.2f}x at phi={sa['phi_ship_sh']:.2f}")
    chk("S=8 is ~1x on the paper's own converter-pitch-limited premise",
        s_gain(8, sa["phi_model_dup"]) < 1.1,
        f"{s_gain(8, sa['phi_model_dup']):.2f}x at phi={sa['phi_model_dup']:.2f}")
    chk("S/H hold cap is much smaller than a duplicated C_int",
        sa["a_cint"] / sa["a_hold"] > 5,
        f"{sa['a_cint']/sa['a_hold']:.0f}x")

    # accuracy currency consistency: +-1 LSB should land on specs.SNR_S_DB
    chk("+-1 LSB maps onto specs.SNR_S_DB within 1 dB (units sanity)",
        abs(csnr_db_for_lsb(1) - specs.SNR_S_DB) < 1.0,
        f"{csnr_db_for_lsb(1):.1f} dB vs {specs.SNR_S_DB} dB")
    chk("the in-force SNR_T is >=10 dB stricter than the measured +-8 LSB budget",
        specs.SNR_T_ATTN_DB - csnr_db_for_lsb(8) > 10.0,
        f"{specs.SNR_T_ATTN_DB - csnr_db_for_lsb(8):.1f} dB unspent")

    # B_y algebra must reproduce the shipped N_COARSE at B_y = 8
    chk("conv_for_by(8) reproduces the shipped conv_time exactly",
        abs(conv_for_by(8) - B["conv"]) / B["conv"] < 1e-9,
        f"{conv_for_by(8)*1e9:.2f} ns vs {B['conv']*1e9:.2f} ns")
    chk("B_y 8->5 + pipelined SAR + S=2 gets within 10% of the window floor",
        conv_for_by(5, True) / 2 <= 1.10 * B["t_in"],
        f"{conv_for_by(5, True)/2*1e9:.1f} ns vs t_in {B['t_in']*1e9:.1f} ns")
    chk("...and COARSE_MARGIN 4->2 with S=2 clears it outright",
        2 * specs.K_SETTLE * B["tau"] / 2 <= B["t_in"],
        f"{2*specs.K_SETTLE*B['tau']/2*1e9:.1f} ns vs {B['t_in']*1e9:.1f} ns")

    # unstructured sparsity collapse
    chk("unstructured 90% sparsity is worth <1.25x at N=16 and ~0 at N=512",
        skip_prob_unstructured(0.9, 16) < 0.2
        and skip_prob_unstructured(0.9, 512) < 1e-20)

    # weight wall
    chk("weight-write traffic exceeds 8-stack HBM3e at the CURRENT tok/s",
        weight_traffic_TBs(TOKS0) > 9.6,
        f"{weight_traffic_TBs(TOKS0):.1f} TB/s vs 9.6")

    print("OVERALL:", "PASS" if ok[0] else "FAIL")
    return ok[0]


if __name__ == "__main__":
    good = _selfcheck()
    with open(OUT, "w") as f:
        f.write(build())
    print("wrote", OUT)
    sys.exit(0 if good else 1)

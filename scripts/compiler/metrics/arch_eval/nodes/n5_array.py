"""N5 array geometry & analog accuracy (ASAP7). Doc: docs/src/content/Project/ArchResearch/nodes/N5.md

Geometry: R rows summed per conversion, C logical outputs, S columns per ADC, plus the
physical extras model.py only knows as "checksum" columns (it has no topology key):
  phys extras = ABFT checksum (chk) + reference columns (pseudo-differential, m_ref wide)
              + the complement column of every column (fully differential).
A differential pair is converted by one ADC, so adc_share doubles with the column count.

Column signal (passive charge share, 27g2 Fig.): V_col = a V_exc sum(x_j w_j)/R with x, w
normalized to full scale. For independent products of rms rho:
  v_sig = g a V_exc rho / sqrt(R)        g = 2 differential, 1 single-ended            (V)
  a     = C_col / (C_col + C_par)        C_par = column wire + ADC input C_in           (27g2: parasitics divide signal and noise alike)
rho is an OPERAND STATISTIC, measured here on the repo's SmolLM2 tensors
(scripts/compiler/out/{acts,programming}, per R-row block): as-quantized (per-tensor INT8 x,
INT4 W) rho = 0.017-0.040 (median 0.037); after an offline random rotation of K and per-token
INT8 / per-64-group INT4 requantization rho = 0.12-0.17 (measured), ~0.10 projected for
Llama-3-8B (wider K -> larger max/rms). rho sets every dB below: thermal SNR is ~ rho^2.
rho_mode "block": rotated (Gaussian) operands with the activation AND weight scale shared per
R-row block (MX-style; the column sum needs one x scale per block): rho(R) = 1/m(R)^2,
m(n) = E[max |z|] of n standard normals (derived order statistic; m(64)^-2 = 0.148 vs the
measured 0.12-0.17 at g64 above). Short blocks raise rho: R32 0.17, R128 0.12, R1024 0.09.
  w_block > R decouples the weight scale (HBM bytes 8/(w_block wbits)) from the row tile; the x
  scale is computed on die per R rows (free in HBM): rho = 1/(m(R) m(w_block)) (derived).
  Scale format: a scale rounded UP to a coarse grid leaves the block max at u <= 1 of full scale,
  rho x sqrt(E[u^2]) per operand: exact 1, E4M3 0.957 (-0.38 dB), E8M0 0.736 (-2.67 dB; u log-uniform
  on (1/2, 1], E[u^2] = 0.75/ln 4) (derived). Default: x exact (on die), w E4M3 (1 byte, a real
  dequant multiply on the rail that the scorer charges, not a shift).
Converter range: |x|, |w| <= 1 after any scaling, so |sum x w| <= R: the partial is HARD-bounded at
  k_hard = sqrt(R)/rho sigma (derived). The range is min(k_sigma, k_hard): N8's measured 16-32 sigma
  clip requirement (per-tensor R128 partials) cannot bind below k_hard, where nothing clips (9.4 sigma
  at R8 block-scaled with an E4M3 w scale, 18 at R16, 33 at R32). n8's gate still sees k_sigma (>= q_clip_sigma).

Error terms (powers relative to v_sig^2, reciprocals add: 27g1):
  thermal   n f_acc kT / C_tot                      27g2, 6b1; n = 2 diff, 1 + 1/m_ref pseudo;
            f_acc = significance-accumulation noise factor (1 = one share per word). The measured
            bit-serial equal-share h=(h+z)/2 from the LSB plane gives h_B = sum z_k 2^-(B-k), the same
            binary weighting as a word-level drive (no extra signal halving), and its repeated-share
            noise settles at kT/(2C)/(1-1/4) = (2/3) kT/C plus the per-plane sampling: f_acc ~ 1.5 (derived;
            the earlier f_acc 4 double-counted a halving)
  mismatch  1/sigma_u^2, sigma_u = sigma_1fF/sqrt(Cu)  27i1 (static; trainable/calibratable, kept as noise)
  settle    exp(2 t_slot/tau_col)/2                 column redistribution, slowest mode of an
            open RC line tau_col = r c L^2/pi^2 (L = R x pitch, /G^2 hierarchical, 27f9);
            r = R_sq / (strap_frac x pitch): the column strap widens with the cell pitch
            (R_sq = min-width wire r x 18 nm, MEJ 36 nm M2 pitch; M6 option 12 ohm/um x 32 nm)
            The initial charge spread projects onto that mode with rms ~ sqrt(2/R) V_cell, so
            the residual is data-dependent noise, not a gain (derived here). Hierarchical options
            also set n2's share_fins = 8 G (one 8-fin share switch per segment: the conductance
            that comes with the capacitance, 27f9); their gate drive is not charged by n2 (~8 fJ
            per column per plane at G 32, < 0.01 fJ/MAC at R 1024). Strapped (M6) options also set
            n2's wire_x = 20 (its column-wire width multiple: a 30 %-of-pitch M6 strap vs a min M2 wire)
  row RC    per-column static gain eps_row = exp(-t_slot/tau_row), tau_row = (Ron/fins + r L_row/2) C_row
            over one driver segment of row_seg phys columns (re-drivers, REPO-B F38; their area is not
            in model.py's periphery term: ~R x phys/row_seg x 8 fins, < 1 % of the tile);
            removed by per-column digital gain trim (27d7, 21i1) to cal_res; > 10 % = range loss -> fail
  col-col   1/(2 eps_cc^2)   two neighbours, independent signals (15o1/15o2: shield ~1/42); diff x0.1 (twist, 3a1)
  row->col  (rho / (eps_rc (VDD/V_exc) x_rms))^2    input-line toggles couple an x-only term
            (20w6a); a reference column or differential pair subtracts it to rej_cm
  inject    sigma = k_inj 0.5 Cgg_share VDD / C_tot  residual signal-dependent share-switch charge
            (27g2 / Gonugondla eq. 23, 18o1a dummies); bottom-plate drive makes the cell switches
            input-independent (18p1); diff x rej_cm
  cap C(V)  MOS-gate units (n3 mos_binary): delta = (C_up - C_dn)/(C_up + C_dn) from n3's measured
            C(V) adds delta sum|x w| (even order); 1/(delta^2 (1 - kappa)) after per-column trim and
            per-token scaling, + kappa R without trim; differential x rej_cm, SE/pseudo not rejected
  mismatch  uses n3's MOS unit sigma (Vt-based) when the cell is MOS, else the MOM law above
  cap odd   amplitude (multi-level) row drive into MOS-gate units (n4 enc amp/nib_amp): the pair
            cancels even order only; the odd (cubic) part of Q(V) = int C dV from n3's measured C(V)
            over [v_inv, cap_rail] is an INL the trim cannot remove: SNR = E[(s x)^2]/E[e(x)^2],
            x the block-normalized input, s the least-squares gain (derived; binary drive: 0)
  ref droop 1/eps_ref^2   data-dependent reference droop = gain noise (24n5)
  xtalk     eps_cc after digital cancellation: coupling is linear and static, so the rail can undo it
            per die (y = (I+E)^-1 y_meas, two neighbour MACs per output); eps_cc x xtalk_cancel
  ADC       12 4^B / (2 k)^2, k = min(k_sigma, k_hard) (27h6 +-k sigma range; B = n6 effective bits) and Gaussian
            clipping 1/(2[(1+k^2)Q(k) - k phi(k)]): a LOWER bound only; the measured partials are
            heavy-tailed (+-4 sigma collapses the proxy, N8 sweep.md), so n8 requires k_sigma >= q_clip_sigma
            (dropped when k = k_hard: nothing can clip). exact_conv: the ADC LSB is one product unit
            (bit-plane x slice partials), quantization is exact and the ADC/clip terms vanish
Converter range Vc = 2 k v_sig. A differential pair is one conversion but model.py counts
two (phys columns), so the returned range is sqrt(2) x the true one: for a 1/Delta^2 energy law
(27h1 r^2 term, n6 quiet decisions) two such conversions cost exactly one true conversion, and
their averaged noise equals its noise, so the ADC term 12 4^B/(2k)^2 stays exact (switching
energy is double counted: conservative).
All numbers projected unless the provenance says measured/derived.
"""
import functools
import math

from arch_eval import asap7 as k

# k_sigma = the range REQUESTED by n8 (bundle 16, g43 32 sigma, measured heavy tails on per-tensor R128
# partials); the range priced is min(k_sigma, k_hard). 32 satisfies every n8 gate and costs nothing
# where k_hard < 32 (block-scaled R <= 32). Scoring sets it per gate. n5 wins the merge over n4's k_sigma.
BASE = dict(rows=128, cols=64, adc_share=8, checksum=1, topo="diff", m_ref=4, segments=1,
            col_rsq_ohm=None, strap_frac=0.1, rho=0.037, x_rms=0.10, k_sigma=32.0, f_acc=1.0,
            c_in_fF=20.0, eps_cc=0.005, xtalk_cancel=1.0, w_block=0, x_scale="exact", w_scale="e4m3",
            exact_conv=False, eps_rc=0.001, rej_cm=0.05, k_inj=0.05,
            eps_ref=0.002, row_fins=8, row_seg=32, cal=True, cal_res=0.05,
            merge_load=None, c_in_mode=None, sel_fins=16, cmp_fins=16, pool_scale=None, pkt_fins=4, ra_fins=16,
            dq_um2=30.0, dq_share=1, dq_e_mac=2.0)
# Round 2 (A3, N5_r2.md). Both keys default to the round-1 behaviour (numbers of every older option unchanged):
#  merge_load  None = the 1:16 slice merge (n4 f_merge) loads nothing (round-1 overclaim); "twostep" = n4's merge
#              (LSB column shared onto C_x, then C_x onto the MSB column: load C_x = s C_L/(1-s)); "bridge" = a series
#              bridge cap C_b = s C_L/(1-s) between the LSB and MSB top nodes (one event, no extra slot: load s C_L).
#              s = 1/(16 cu_lsb) is the LSB charge fraction the 1:16 weight needs (W8 = 16 W_hi + W_lo; 3+4 split).
#  c_in_mode   None = c_in_fF (20 fF, the round-1 sampling-ADC placeholder); "direct" = the direct (retained-column)
#              SAR's real node: own switches + comparator gate + pooled bus, per column (ESPice E3, measured caps).
#              Critic round: the direct node also carries the ADC's own input-side devices on the shared bus: the
#              charge-injection packet switches (2 per decision, trial + kept, pkt_fins each, n6 dac "inj") and the
#              residue-amp input pair (ra_fins, n6 fine "ra"). A sampled or bottom-plate CDAC is priced by n6 itself.
#  pool_scale  None = round 1 (n6 cascade_K tiles pooled with the per-R-row block rho: physically inconsistent, a
#              charge pool has no per-tile scale); "shared" = the K pooled tiles share x and w scales, so the scale
#              block is K R rows (rho(K R), scale bytes per K R): the consistent pooled conversion (N5_r2.md).
# Per-fin caps, ESPice E3 (BSIM-CMG TT, 100 MHz AC; scratchpad a3/e3_cap.py): off drain 0.0113, on switch from one
# side 0.0263 fF/fin (measured, intrinsic device). Input gate: E3 biased it at VGS 0.25 V (VS 0.1, critic); E3b
# (a3/e3b_cap.py) re-measures it at the evaluation bias, VS 0: C_GATE_MEAS below (the larger of VGS 0.35 V
# saturation / triode). x2 for MOL/contact and local-wire extrinsics, which the bare BSIM-CMG card lacks (projected).
LAYOUT_X = 2.0
C_GATE_MEAS = 0.0390          # E3b: VGS 0.35 V, VS 0: 0.0349 saturated, 0.0390 triode (end of evaluation); 0.0598 at VGS 0.7
C_OFF_FIN, C_ON_FIN, C_GATE_FIN = 0.0113 * LAYOUT_X, 0.0263 * LAYOUT_X, C_GATE_MEAS * LAYOUT_X


@functools.lru_cache(maxsize=None)
def _emax(n):
    """E[max |z|] over n iid standard normals: int_0^inf 1 - erf(t/sqrt2)^n dt (midpoint rule)."""
    h = 0.005
    return sum(1 - math.erf((i + 0.5) * h / math.sqrt(2)) ** n for i in range(int(8 / h))) * h


_SCALE_EU2 = {"exact": 1.0, "e4m3": None, "e8m0": 0.75 / math.log(4)}


def _eu2(fmt):
    """E[u^2] of the normalized block max when the scale is rounded up to the format's grid
    (u log-uniform within one grid step). E4M3: 3 mantissa bits, step 2^(e-3)."""
    if _SCALE_EU2.get(fmt) is None:
        n, acc = 400, 0.0
        for i in range(8):                       # mantissa interval [1 + i/8, 1 + (i+1)/8)
            lo, hi = 1 + i / 8, 1 + (i + 1) / 8
            for j in range(n):                   # value log-uniform inside the octave, scale = hi
                v = lo * (hi / lo) ** ((j + 0.5) / n)
                acc += (v / hi) ** 2 * math.log(hi / lo) / n
        _SCALE_EU2[fmt] = acc / math.log(2)
    return _SCALE_EU2[fmt]


def rho_of(p, R):
    if p.get("rho_mode") != "block":
        return p["rho"]
    wb = max(R, int(p.get("w_block") or R))
    xb = max(R, int(p.get("x_block") or R))     # round 2: x scale shared over x_block rows
    if p.get("pool_scale") == "shared":         # K row tiles charge-pooled into one conversion must share x and w
        blk = R * int(p.get("cascade_K", 1) or 1)   # scales: the scale block is the pooled K R rows (N5_r2.md)
        xb, wb = max(xb, blk), max(wb, blk)
    return math.sqrt(_eu2(p.get("x_scale", "exact")) * _eu2(p.get("w_scale", "e4m3"))) / (_emax(xb) * _emax(wb))


def k_range(p, R):
    """Converter range in sigma: min(k_sigma, k_hard = sqrt(R)/rho) (|sum x w| <= R, derived)."""
    return min(p["k_sigma"], math.sqrt(R) / rho_of(p, R))


def scale_bytes_frac(p, wbits):
    """HBM weight-byte overhead of one 8-b weight scale per w_block (block mode only)."""
    if p.get("rho_mode") != "block":
        return 0.0
    blk = int(p["rows"]) * (int(p.get("cascade_K", 1) or 1) if p.get("pool_scale") == "shared" else 1)
    return 8 / (max(blk, int(p.get("w_block") or p["rows"])) * wbits)


def dequant(p, t):
    """Per-pass cost of turning ADC codes into scaled partials (critic round; block mode only). Each conversion
    needs code x w_scale (12 x 4-b mantissa multiply + E4M3 exponent shift) and the per-pass x scale, then a wide
    accumulate. One unit per dq_share ADCs (a 12x4 multiply-add settles in well under one t_conv at ASAP7):
    dq_um2 = 30 um2 per unit, projected (12x4 array ~11, 16-b barrel shift ~6, 24-b add + register ~7, x-scale
    apply ~6; ASAP7 FA ~0.2 um2, DFF ~0.3 um2). Energy dq_e_mac rail INT8-MAC equivalents per conversion
    (projected). The x scale per R rows is formed by the rail's quantizer from the wide activation (one rounding,
    not a requantization of per-token INT8): one max over R values per R activations, < 1e-4 of the MACs, not priced
    (ponytail: negligible; price it if activations ever arrive pre-quantized).
    Returns dict(area_um2, e_J) per tile and pass; zero outside block mode."""
    if p.get("rho_mode") != "block":
        return dict(area_um2=0.0, e_J=0.0)
    convs = t["cols"] * (1 if p.get("f_merge") else t["slices"]) / int(p.get("cascade_K", 1) or 1)
    n_u = -(-int(t["n_adc"]) // max(1, int(p["dq_share"])))
    return dict(area_um2=n_u * p["dq_um2"], e_J=convs * p["dq_e_mac"] * t["rail"]["e_att_mac_J"])


def merge_cap_um2(p, t):
    """MOM area of the 1:16 merge cap (C_x or C_b = s C_L/(1-s)), one per side per logical column."""
    if not (p.get("merge_load") and p.get("f_merge") and t["slices"] == 2):
        return 0.0
    cu_lsb = float(p.get("f_cu_lsb", 1.0))
    c_l = t["arr"]["c_col_fF"] * 15 / 7 * cu_lsb
    s = min(1.0, 1 / (16 * cu_lsb))
    return 0.0 if s >= 1 else 2 * t["cols"] * (c_l * s / (1 - s)) / k.get("mom_cap_density_fF_per_um2")


def _o(prov, **kw):
    return dict(params=dict(BASE, **kw), provenance=prov)


M6_RSQ = 12.0 * 0.032   # ohm/sq: CHAR.md M6 12 ohm/um at its 32 nm min width (64 nm pitch, MEJ Table 1)
MEAS = "rho 0.037 / x_rms 0.10 measured on as-quantized SmolLM2 tensors"
ROT = dict(rho=0.10, x_rms=0.26)   # rotated operands: measured 0.12-0.17 on SmolLM2, projected 0.10 at Llama K
ROTP = ("rho 0.10 rotated operands (measured 0.12-0.17 SmolLM2, projected 0.10 Llama K); do NOT combine "
        "with n8 lv_hadamard / bundle_lead (same effect counted twice)")
BLK = dict(rho_mode="block", rows=32, x_rms=0.42)   # x/w scale per row-tile block: rho(R) order statistic
BLKP = ("rho(R) = 1/E[max|z|]^2 with x and w scales per R-row block (MX-style, block = row tile): derived law, "
        "measured on SmolLM2 (R16 0.24, R32 0.175, R64 0.13-0.16, with or without rotation)")
OPTIONS = {
    # A. topology / signed weights at R128 C64 S8, as-quantized operands (repo per-tensor contract)
    "diff_r128c64": _o(f"derived: fully differential pair, {MEAS}; rows = measured sky130 macro height"),
    "se_r128c64": _o("derived: single-ended column, signed bottom-plate excitation (measured sky130 "
                     "topology, IMC_SIZING_RESEARCH); " + MEAS, topo="se"),
    "pseudo_r128c64": _o("derived: single-ended + one 4x-wide reference column per tile (18r1, 3a); " + MEAS,
                         topo="pseudo"),
    # B. same topologies, rotated operands (QuaRot-class), fixed rho 0.10
    "diff_rot": _o("derived: differential, " + ROTP, **ROT),
    "se_rot": _o("derived: single-ended, " + ROTP, topo="se", **ROT),
    "pseudo_rot": _o("derived: pseudo-differential, " + ROTP, topo="pseudo", **ROT),
    # C. block-scaled operands, rho(R): the lead family; every geometry variant is built on it
    "blk_diff_r8_c256_s4": _o("LEAD derived: differential, R8 C256 S4, no checksum column, x scale exact (on die) "
                              "and E4M3 w scale per 8 rows, range min(k, k_hard = 9.4 sigma); joint search over R x C x "
                              "S x n4 {w8a8_lead_amp, w8a8_2slice} (revision 2): best with n4 w8a8_lead_amp + n2 "
                              "charge_rail, at the rail-attention / HBM ceiling (S1-S4 tie within 0.1 %); " + BLKP,
                              **dict(BLK, rows=8, cols=256, x_rms=0.55), adc_share=4, checksum=0),
    "blk_diff_r8_c64_s16": _o("derived: differential, R8 C64 S16 (joint best under n8 g43_lossless); " + BLKP,
                              **dict(BLK, rows=8, x_rms=0.55), adc_share=16, checksum=0),
    "blk_diff_r16_c256_s8": _o("derived: differential, R16 C256 S8 (half the ADC area of the lead); " + BLKP,
                               **dict(BLK, rows=16, cols=256, x_rms=0.48), checksum=0),
    "blk_diff_r32_c256_s32": _o("derived: differential, R32 C256 S32 + ABFT (the TOPS/W-leaning point: 3x the "
                                "lead's TOPS/W at 0.28x its tok/s); " + BLKP, **dict(BLK, cols=256), adc_share=32),
    "blk_diff_r32": _o("derived: differential, R32 C64 S8 (lead family base); " + BLKP, **BLK),
    "blk_se_r32": _o("derived: single-ended, R32; " + BLKP, topo="se", **BLK),
    "blk_pseudo_r32": _o("derived: pseudo-differential, R32; " + BLKP, topo="pseudo", **BLK),
    "blk_diff_r16": _o("derived: differential, R16 (8x the conversions of R128); " + BLKP,
                       **dict(BLK, rows=16, x_rms=0.48)),
    "blk_diff_r64": _o("derived: differential, R64; " + BLKP, **dict(BLK, rows=64, x_rms=0.38)),
    "blk_diff_r128": _o("derived: differential, R128; " + BLKP, **dict(BLK, rows=128, x_rms=0.35)),
    "blk_diff_r256": _o("derived: differential, R256; " + BLKP, **dict(BLK, rows=256, x_rms=0.33)),
    "blk_diff_r512_m6": _o("derived: differential, R512, column strap on M6 (12 ohm/um at 32 nm, CHAR.md), 30 % "
                           "of pitch; " + BLKP, **dict(BLK, rows=512, x_rms=0.31), col_rsq_ohm=M6_RSQ, strap_frac=0.3),
    "blk_diff_r1024_hier": _o("derived: differential, R1024, G = 32 = sqrt(N) segments (27f9) + M6 bus; " + BLKP,
                              **dict(BLK, rows=1024, x_rms=0.30), col_rsq_ohm=M6_RSQ, strap_frac=0.3, wire_x=20.0, segments=32,
                              share_fins=8 * 32),
    "blk_diff_r4096_hier": _o("derived: differential, full-K R4096 (14336 pads 12.5 %), G = 64 + M6 bus; " + BLKP,
                              **dict(BLK, rows=4096, x_rms=0.27), col_rsq_ohm=M6_RSQ, strap_frac=0.3, wire_x=20.0, segments=64,
                              share_fins=8 * 64),
    "blk_diff_c16": _o("derived: lead with 16 logical columns", **dict(BLK, cols=16)),
    "blk_diff_c256": _o("derived: lead with 256 logical columns (repeated row drivers every 32 phys cols)",
                        **dict(BLK, cols=256)),
    "blk_diff_c1024": _o("derived: lead with 1024 logical columns", **dict(BLK, cols=1024)),
    "blk_diff_s2": _o("derived: lead, 2 columns per ADC (pitch match infeasible, 27h4)", **BLK, adc_share=2),
    "blk_diff_s32": _o("derived: lead, 32 columns per ADC", **BLK, adc_share=32),
    "blk_diff_s128": _o("derived: lead, 128 columns per ADC", **BLK, adc_share=128),
    "blk_diff_nochk": _o("derived: lead without the ABFT checksum column", **BLK, checksum=0),
    "blk_diff_unshielded": _o("projected: lead without shield/cage between columns, eps_cc 0.10 (15o)", **BLK,
                              eps_cc=0.10),
    "blk_diff_nocal": _o("derived: lead without per-column gain/offset trim", **BLK, cal=False),
    "blk_diff_bitserial_share": _o("derived: R32 base with the measured bit-serial equal-share significance "
                                   "accumulator (h=(h+z)/2 from the LSB plane = binary weighting, steady-state "
                                   "noise ~(2/3) kT/C + per-plane sampling) -> f_acc 1.5 (was 4: critic-corrected)",
                                   **BLK, f_acc=1.5),
}

# D. Critic-round options (2026-10-05 revision). Keys "score_*" are read by the N5 scorer only
# (design params / format / bit restrictions the option needs); model.py ignores them.
L8 = dict(BLK, rows=8, cols=256, x_rms=0.55, adc_share=4, checksum=0)


def _lsb_r(R):
    """LSB-slice capacitance divisor: its share of output power is f = (4.61 m(R)/127)^2 for
    block-normalized W8 (MSB slice rms 127/(16 m), LSB slice uniform rms 4.61); allow <= 0.5 dB total
    loss, r = 1 + 0.122 (1 + f)/f, half of it spent on the caps (the other half on n4's 2-b ADC drop)."""
    f = (4.61 * _emax(R) / 127) ** 2
    return round((1 + 0.122 * (1 + f) / f) / 2, 1)


OPTIONS.update({
    "blk_diff_r8_c256_s4_e8m0": _o("derived: R8 lead geometry with E8M0 (power-of-two) x AND w scales: dequant is a "
                                   "shift, rho x 0.541 (-2.67 dB per operand)", **dict(L8, x_scale="e8m0", w_scale="e8m0")),
    "blk_diff_r8_c256_s4_e8m0w": _o("derived: R8, exact on-die x scale, E8M0 w scale (rho x 0.736)",
                                    **dict(L8, w_scale="e8m0")),
    "blk_diff_r8_c256_s4_wblk32": _o("derived: R8, x scale per 8 rows on die, w scale per 32 rows in HBM (MX g32): "
                                     "rho 1/(m(8) m(32)), 3.1 % scale bytes instead of 12.5 %", **dict(L8, w_block=32)),
    "blk_diff_r8_c256_s4_lsbthin": dict(_o("derived: R8, W8 LSB slice with 1/r of the capacitance and a 2-b coarser "
                                           "ADC (n4 f_lsb_scaled): block-normalized W8 puts ~0.4 % of the output power "
                                           "in the LSB slice (N4's falsified 4-b drop was per-channel weights)",
                                           **dict(L8, f_lsb_scaled=True, f_lsb_drop=2)), score_params=dict(_lsb_r=_lsb_r(8))),
    "blk_diff_r8_exact": dict(_o("derived: exact low-resolution conversion, R8, 2-b input planes x 4-b slices "
                                 "(4 conversions per word per slice), ADC LSB = one product unit (|partial| <= 360): "
                                 "no SNR->PPL gate risk; needs sigma_n <= LSB/8 = 48.7 dB per conversion (rho 0.30 "
                                 "projected for bit-plane x slice operands)",
                                 **dict(L8, rho_mode=None, rho=0.30, exact_conv=True, f_enc="bitserial", input_planes=4)),
                              score_params=dict(q_snr_target_db=48.7, q_credit_db=0.0), score_bits=[10, 12, 14],
                              score_fmts=["w8a8_2slice"]),
    "blk_diff_unshielded_xcancel": _o("projected: R32 base, no shield (eps_cc 10 %) + per-die digital crosstalk "
                                      "cancellation on the rail to 5 % residual (linear static coupling)", **BLK,
                                      eps_cc=0.10, xtalk_cancel=0.05),
    "blk_diff_r256_wseg8": dict(_o("derived: R256 C256 S2 with an 8-segment write bitline (8 write drivers per "
                                   "column, 0.6 um2 each): t_load and refresh occupancy / 8", **dict(BLK, rows=256,
                                   cols=256, adc_share=2, checksum=0, x_rms=0.33, write_segments=8))),
    "blk_diff_r512_wseg16": dict(_o("derived: R512 C256 S2, 16 write segments, M6 strap", **dict(BLK, rows=512, cols=256,
                                    adc_share=2, checksum=0, x_rms=0.31, write_segments=16), col_rsq_ohm=M6_RSQ,
                                    strap_frac=0.3)),
    "blk_diff_r1024_hier_wseg32": dict(_o("derived: R1024 hierarchical (G 32) + 32 write segments", **dict(BLK, rows=1024,
                                          cols=256, adc_share=2, checksum=0, x_rms=0.30, write_segments=32),
                                          col_rsq_ohm=M6_RSQ, strap_frac=0.3, wire_x=20.0, segments=32, share_fins=8 * 32)),
})
# E. Round 2 (A3, N5_r2.md): the round-1 pick's tile (R8 C256 S4, n4 merge) with the merge load and the direct-SAR
# node priced, then faster accumulation. FAST = what a ~0.4 ns plane slot needs from n5's own terms: row drivers
# 32 fins every 16 phys columns (row_gain stays >= 60 dB), an M7 column strap over the MOM6 caps (30 % of pitch,
# M6-class 0.384 ohm/sq; n2 wire_x 20) and n2 share_fins 32 (ESPice E1: tau 9.8 ps, 13-b settle 86 ps per share).
R2 = dict(L8, merge_load="bridge", c_in_mode="direct", pool_scale="shared")
FAST = dict(row_fins=32, row_seg=16, col_rsq_ohm=M6_RSQ, strap_frac=0.3, wire_x=20.0, share_fins=32)
R2P = "ESPice E2/E2b (linear-network merge topology check, not a block verification) / E3/E3b (node caps), N5_r2.md"
OPTIONS.update({
    "r2_l8_twostep": _o("derived: round-1 pick tile with n4's two-step 1:16 merge load priced (C_x = C_L/3 = 10 fF on "
                        "the MSB node), c_in 20 fF: the honest round-1 tile; " + R2P, **dict(L8, merge_load="twostep")),
    "r2_l8_bridge": _o("derived: as r2_l8_twostep with a bridge-cap merge (C_b = C_L/3 in series, load 7.5 fF, one event: "
                       "n4 still charges its +1 merge slot, see interactions); " + R2P, **dict(L8, merge_load="bridge")),
    "r2_l8_twostep_direct": _o("derived: two-step merge priced + the direct-SAR column node (own switches, 1/K of the "
                               "pooled bus, comparator gate; measured caps x2 layout) instead of 20 fF; " + R2P,
                               **dict(L8, merge_load="twostep", c_in_mode="direct")),
    "r2_l8_bridge_direct": _o("derived: bridge merge + direct node (the A3 accuracy base); " + R2P, **R2),
    "r2_fast_s4": _o("derived: A3 base + FAST row/column drive at S4 (pass stays conversion-bound); " + R2P,
                     **dict(R2, **FAST)),
    "r2_fast_s2": _o("derived: A3 base + FAST, 2 columns per ADC (2 conversion rounds); " + R2P,
                     **dict(R2, **FAST, adc_share=2)),
    "r2_fast_s1": _o("derived: A3 base + FAST, one ADC per column pair (1 round: the converter count buys the speed); "
                     + R2P, **dict(R2, **FAST, adc_share=1)),
    "r2_fast_s2_c128": _o("derived: r2_fast_s2 at 128 logical columns (half the row line)", **dict(R2, **FAST, adc_share=2,
                          cols=128)),
    "r2_fast_s2_c512": _o("derived: r2_fast_s2 at 512 logical columns", **dict(R2, **FAST, adc_share=2, cols=512)),
    "r2_fast_s2_r4": _o("derived: r2_fast_s2 at R4 (rho(4) block law, k_hard 7 sigma)", **dict(R2, **FAST, adc_share=2,
                        rows=4, x_rms=0.6)),
    "r2_fast_s2_r16": _o("derived: r2_fast_s2 at R16", **dict(R2, **FAST, adc_share=2, rows=16, x_rms=0.48)),
    "r2_fast_s2_se": _o("derived: r2_fast_s2 single-ended (half the caps, -3 dB thermal, no CM rejection)",
                        **dict(R2, **FAST, adc_share=2, topo="se")),
    "r2_fast_s2_pseudo": _o("derived: r2_fast_s2 pseudo-differential (one 4x reference column per tile)",
                            **dict(R2, **FAST, adc_share=2, topo="pseudo")),
})
DEFAULT = "blk_diff_r8_c256_s4"
SWEEP = dict(rows=[8, 16, 32, 64, 128, 256, 512, 1024], cols=[32, 64, 128, 256], adc_share=[1, 2, 4, 8, 32, 128],
             k_sigma=[4.0, 16.0, 32.0])


def geometry(p):
    R, C, chk, topo = int(p["rows"]), int(p["cols"]), int(p.get("checksum", 1)), p.get("topo", "diff")
    ref = int(p.get("m_ref", 4)) if topo == "pseudo" else 0
    comp = C + chk + ref if topo == "diff" else 0          # complement of every column
    share = int(p["adc_share"]) * (2 if topo == "diff" else 1)
    return dict(rows=R, cols=C, adc_share=share, checksum=chk + ref + comp,
                abft=chk, ref_cols=ref, topo=topo)


def _db(x):
    return 10 * math.log10(max(x, 1e-30))


def _cell(p, vdd, fmt):
    """The n3 cell this design uses (area, MOS-cap data); None if n3 is unavailable."""
    try:
        from arch_eval.nodes import n3_cell
        return n3_cell, n3_cell.cell(p, vdd, fmt)
    except Exception:  # noqa: BLE001  (n3 is another researcher's file: degrade to the MOM estimate)
        return None, None


def _pitch_um(p, arr, R, vdd=0.7, fmt=None):
    """Column pitch along the column = sqrt(one weight-slice cell); n3's area when available,
    else the MOM BEOL law with a 0.45 um2 FEOL floor."""
    _, c = _cell(p, vdd, fmt) if fmt else (None, None)
    if c:
        return math.sqrt(c["area_um2_per_weight"] / max(1, fmt["slices"]))
    return math.sqrt(max(arr["c_col_fF"] / R / k.get("mom_cap_density_fF_per_um2"), 0.45))


def cap_nl_delta(p, vdd):
    """Even-order charge asymmetry of a MOS-gate unit driven cm -> VDD vs cm -> V_inv (n3's levels):
    delta = (C_up - C_dn)/(C_up + C_dn) from n3's measured C(V); 0 for MOM (linear, 27i1)."""
    m, c = _cell(p, vdd, dict(wbits=4, slices=1, abits=8, input_planes=6))
    if not c or p.get("cap") != "mos_binary":
        return 0.0
    vi = p["v_inv"]
    cm = (vi + vdd) / 2
    up, dn = m.mos_c_avg_aF(cm, vdd), m.mos_c_avg_aF(vi, cm)
    return (up - dn) / (up + dn)


def merge_load_fF(p, arr):
    """Extra capacitance the 1:16 slice merge hangs on the MSB column node (fF; see BASE notes)."""
    mode = p.get("merge_load")
    if not mode or not p.get("f_merge"):
        return 0.0
    cu_lsb = float(p.get("f_cu_lsb", 1.0))
    c_l = arr["c_col_fF"] * 15 / 7 * cu_lsb          # ponytail: W8 3+4 split only (the one merged format)
    s = min(1.0, 1 / (16 * cu_lsb))
    if s >= 1.0:                                      # LSB units already 1/16: share the whole LSB column
        return c_l
    return s * c_l if mode == "bridge" else s * c_l / (1 - s)


def c_in_fF(p, geo, pitch):
    """ADC-side capacitance on one column node (fF). direct: the column's own share (share_fins) and reset
    (8 fins) switch drains, its on select switch, and 1/K of the pooled bus: S x K off select drains, the
    comparator input pair (cmp_fins) and the bus wire (K R pitch along + 4 S pitch across: 2 slices x 2 sides)."""
    if p.get("c_in_mode") != "direct":
        return p["c_in_fF"]
    S, K, R, sf = int(p["adc_share"]), int(p.get("cascade_K", 1) or 1), geo["rows"], p["sel_fins"]
    own = (p.get("share_fins", 8) + 8) * C_OFF_FIN + sf * C_ON_FIN
    bus = S * K * sf * C_OFF_FIN + p["cmp_fins"] * C_GATE_FIN + (K * R + 4 * S) * pitch * k.get("wire_c_fF_per_um")
    if p.get("adc") == "sar_direct" and p.get("dac", "inj") not in ("bp",):           # packet switch drains
        bus += 2 * int(p.get("adc_bits", 8)) * p["pkt_fins"] * C_OFF_FIN
    if p.get("adc") == "sar_direct" and p.get("fine") == "ra":                         # residue-amp input pair
        bus += p["ra_fins"] * C_GATE_FIN
    return own + bus / K


def _column(p, geo, arr, vdd=0.7, fmt=None):
    R = geo["rows"]
    pitch = _pitch_um(p, arr, R, vdd, fmt)
    L = R * pitch
    c_wire = L * k.get("wire_c_fF_per_um")
    c_par = c_wire + c_in_fF(p, geo, pitch) + merge_load_fF(p, arr)
    c_tot = arr["c_col_fF"] + c_par
    a = arr["c_col_fF"] / c_tot
    g = 2.0 if geo["topo"] == "diff" else 1.0
    v_side = a * arr["v_exc_V"] * rho_of(p, R) / math.sqrt(R)
    return dict(pitch_um=pitch, L_um=L, c_tot_fF=c_tot, atten=a, v_side_V=v_side, v_sig_V=g * v_side,
                c_par_fF=c_par)


def v_range(p, geo, arr):
    """Converter input range (V): +-k of the column signal, k = k_range (min(k_sigma, k_hard)). Differential: the true range is
    2 x the per-side one; model.py converts the pair twice, so the range handed over is sqrt(2) x
    true, which makes two 1/Delta^2-law conversions cost one true differential conversion and
    keeps the ADC SNR term below exact (two conversions of noise sqrt(2) x, averaged)."""
    col = _column(p, geo, arr)
    vc = 2 * k_range(p, geo["rows"]) * col["v_sig_V"]
    return vc * math.sqrt(2) if geo["topo"] == "diff" else vc


def cap_odd_snr(p, R):
    if p.get("cap") != "mos_binary":
        return math.inf
    return _cap_odd(p["v_inv"], p["cap_rail"], R)


@functools.lru_cache(maxsize=None)
def _cap_odd(vi, rail, R):
    """SNR of the odd-order (cubic) INL of a MOS-gate unit under amplitude drive: the pair drives
    cm +- v, v = x (rail - v_inv)/2, so the column difference is the odd part of Q(v) = int C dV
    (n3 measured C(V)). Gain-trimmed least-squares fit over x = z / E[max|z|] (block-normalized,
    clipped to [-1, 1]). inf for MOM or binary drive."""
    try:
        from arch_eval.nodes import n3_cell as m
    except Exception:  # noqa: BLE001
        return math.inf
    cm, half = (vi + rail) / 2, (rail - vi) / 2

    def q(v):                                     # aF*V per fin, cm -> cm + v
        n = 40
        return sum(m._interp(m.C_MOS_AF_PER_FIN, cm + v * (i + 0.5) / n) for i in range(n)) / n * v
    mR, n, sxx, sxy, syy = _emax(R), 200, 0.0, 0.0, 0.0
    for i in range(n):                            # z quantiles of N(0,1), weights uniform
        z = math.sqrt(2) * _erfinv(2 * (i + 0.5) / n - 1)
        x = max(-1.0, min(1.0, z / mR))
        y = q(x * half) - q(-x * half)
        sxx, sxy, syy = sxx + x * x, sxy + x * y, syy + y * y
    s_ = sxy / sxx
    err = max(syy - s_ * sxy, 1e-30)              # residual after the best gain
    return s_ * s_ * sxx / err


def _erfinv(y):
    lo, hi = -6.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if math.erf(mid) < y else (lo, mid)
    return (lo + hi) / 2


def _clip_snr(kk):
    q = 0.5 * math.erfc(kk / math.sqrt(2))
    phi = math.exp(-kk * kk / 2) / math.sqrt(2 * math.pi)
    return 1 / max(2 * ((1 + kk * kk) * q - kk * phi), 1e-30)


def accuracy(p, vdd, geo, arr, adc, fmt):
    col = _column(p, geo, arr, vdd, fmt)
    topo, R = geo["topo"], geo["rows"]
    kT = k.get("kT_300K_J")
    s2 = col["v_sig_V"] ** 2
    n_th = {"diff": 2.0, "se": 1.0, "pseudo": 1.0 + 1.0 / max(1, p["m_ref"])}[topo]
    cm = p["rej_cm"] if topo in ("diff", "pseudo") else 1.0
    thermal = s2 / (n_th * p["f_acc"] * kT / (col["c_tot_fF"] * 1e-15))
    _, cell = _cell(p, vdd, fmt)
    sig_u = (cell or {}).get("mos_unit_sigma") or \
        k.get("cap_match_sigma_pct_at_1fF") / 100 / math.sqrt(p.get("cu_fF", 1.0))
    # MOS-cap C(V): even-order term delta sum|x w|; per-token scaling + column trim leave the
    # random part (1 - kappa), kappa = (E|xw|)^2/E(xw)^2 = (2/pi)^2 for Gaussian products; without
    # trim the mean part kappa R also stays. Only a differential pair cancels it (to rej_cm, 18c1, 6x).
    dl = cap_nl_delta(p, vdd) * (p["rej_cm"] if topo == "diff" else 1.0)
    kap = (2 / math.pi) ** 2
    nl = dl ** 2 * ((1 - kap) + (0 if p["cal"] else kap * R))
    # column redistribution settling (data-dependent residual)
    kk = k_range(p, R)
    t_slot = arr.get("slot_ns", arr["t_word_ns"] / max(1, fmt["input_planes"]))
    rsq = p["col_rsq_ohm"] or k.get("wire_r_ohm_per_um") * 0.018                # ohm/sq
    r_col = rsq / (p["strap_frac"] * col["pitch_um"])                            # ohm/um
    c_len = col["c_tot_fF"] / col["L_um"] * 1e-15                       # F/um
    tau_col = r_col * c_len * (col["L_um"] / p["segments"]) ** 2 / math.pi ** 2 * 1e9   # ns
    if p["segments"] > 1:                                               # global bus joins G segment nodes
        tau_col += r_col * c_len * col["L_um"] ** 2 / math.pi ** 2 * 1e9 / p["segments"]
    settle = math.exp(min(2 * t_slot / tau_col, 600)) / 2
    # row (bottom-plate drive) line: per-column static gain error
    phys_row = min((geo["cols"] + geo["checksum"]) * fmt["slices"], p["row_seg"])   # repeated row drivers
    L_row = phys_row * col["pitch_um"]
    c_row = phys_row * arr["c_col_fF"] / R * 1e-15 + L_row * k.get("wire_c_fF_per_um") * 1e-15
    r_drv = k.get("switch_ron_ohm_per_fin", vdd=vdd) / p["row_fins"]
    tau_row = (r_drv + k.get("wire_r_ohm_per_um") * 0.018 / (p["strap_frac"] * col["pitch_um"]) * L_row / 2) \
        * c_row * 1e9
    eps_row = math.exp(-t_slot / tau_row)
    row_err = eps_row * (p["cal_res"] if p["cal"] else 1.0)
    # coupling and injection
    cc = p["eps_cc"] * (0.1 if topo == "diff" else 1.0) * p.get("xtalk_cancel", 1.0)
    rc = p["eps_rc"] * (vdd / arr["v_exc_V"]) * p["x_rms"] * cm
    q_inj = p["k_inj"] * 0.5 * p.get("share_fins", 8) * k.get("nfet_cgg_per_fin_aF") * 1e-18 * vdd / (col["c_tot_fF"] * 1e-15) * cm
    off = 0.0 if p["cal"] else 0.5 * 8 * k.get("nfet_cgg_per_fin_aF") * 1e-18 * vdd / (col["c_tot_fF"] * 1e-15) * cm
    parts = dict(thermal=_db(thermal), mismatch=_db(1 / sig_u ** 2), settle=_db(settle),
                 row_gain=_db(1 / max(row_err, 1e-15) ** 2), coupling=_db(1 / (2 * cc ** 2)),
                 row_coupling=_db(rho_of(p, R) ** 2 / max(rc, 1e-15) ** 2),
                 injection=_db(s2 / (q_inj ** 2 + off ** 2)), cap_nl=_db(1 / max(nl, 1e-30)), ref_droop=_db(1 / p["eps_ref"] ** 2),
                 adc=_db(12 * 4 ** adc["bits"] / (2 * kk) ** 2), clip=_db(_clip_snr(kk)))
    if kk < p["k_sigma"]:                                               # hard-bounded: nothing clips
        del parts["clip"]
    if p.get("exact_conv"):                                             # LSB = one product unit: exact
        del parts["adc"]
        parts.pop("clip", None)
    if fmt.get("enc") in ("amp", "nib_amp") and p.get("cap") == "mos_binary":
        parts["cap_odd"] = _db(cap_odd_snr(p, R))
    if eps_row > 0.10:                                                  # far columns lose >10 % of range
        parts["row_gain"] = 0.0
    total = -_db(sum(10 ** (-v / 10) for v in parts.values()))
    return dict(snr_db=total, parts_db=parts, adc_range_sigma=kk, v_signal_rms_V=col["v_sig_V"], atten=col["atten"],
                tau_col_ns=tau_col, tau_row_ns=tau_row, t_slot_ns=t_slot, eps_row=eps_row,
                pitch_um=col["pitch_um"], c_tot_fF=col["c_tot_fF"], c_par_fF=col["c_par_fF"],
                merge_load_fF=merge_load_fF(p, arr))


if __name__ == "__main__":   # self-check: R-independence of thermal SNR, diff +3 dB, rho^2 law
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    arr = dict(v_exc_V=0.175, c_col_fF=128 * 7.0, slot_ns=13.4, t_word_ns=80.0)
    fmt = dict(slices=1, input_planes=6)
    adc = dict(bits=8)
    pd, ps = OPTIONS["diff_rot"]["params"], OPTIONS["se_rot"]["params"]
    ad = accuracy(dict(pd, cu_fF=1.0), 0.7, geometry(pd), arr, adc, fmt)
    a_s = accuracy(dict(ps, cu_fF=1.0), 0.7, geometry(ps), arr, adc, fmt)
    assert abs(ad["parts_db"]["thermal"] - a_s["parts_db"]["thermal"] - 3.01) < 0.05
    lo = accuracy(dict(pd, cu_fF=1.0, rho=0.05), 0.7, geometry(pd), arr, adc, fmt)
    assert abs(ad["parts_db"]["thermal"] - lo["parts_db"]["thermal"] - 6.02) < 0.05
    g = geometry(pd)
    assert g["checksum"] == 1 + 65 and g["adc_share"] == 16
    pb = OPTIONS[DEFAULT]["params"]                                     # hard-bounded range at R8
    assert abs(k_range(pb, 8) - math.sqrt(8) / rho_of(pb, 8)) < 1e-9 and k_range(pb, 8) < pb["k_sigma"]
    assert abs(_eu2("e8m0") - 0.75 / math.log(4)) < 1e-12 and 0.90 < _eu2("e4m3") < 0.93
    assert abs(rho_of(dict(pb, w_block=32), 8) / rho_of(pb, 8) - _emax(8) / _emax(32)) < 1e-9
    assert 50 < _db(_cap_odd(0.45, 0.7, 8)) < 70                        # odd-order INL under amplitude drive
    lm = dict(merge_load="bridge", f_merge=True, f_cu_lsb=0.25)                # round 2 (A3)
    assert abs(merge_load_fF(lm, dict(c_col_fF=56.0)) - 7.5) < 1e-9                  # s C_L, C_L = 30 fF
    assert abs(merge_load_fF(dict(lm, merge_load="twostep"), dict(c_col_fF=56.0)) - 10.0) < 1e-9
    assert merge_load_fF(dict(lm, merge_load=None), dict(c_col_fF=56.0)) == 0.0
    pp = dict(pb, pool_scale="shared", cascade_K=4)
    assert abs(rho_of(pp, 8) - rho_of(dict(pb, x_block=32, w_block=32), 8)) < 1e-12 and rho_of(pp, 8) < rho_of(pb, 8)
    assert abs(scale_bytes_frac(pp, 8) - 8 / (32 * 8)) < 1e-12
    gd = OPTIONS["r2_l8_bridge_direct"]["params"]
    assert 3.0 < c_in_fF(dict(gd, share_fins=16, cascade_K=4), geometry(gd), 1.71) < 10.0   # pick node: ~7 fF
    ra = dict(gd, share_fins=24, adc="sar_direct", fine="ra", adc_bits=12)                  # critic: + packets + RA
    assert c_in_fF(ra, geometry(gd), 1.71) - c_in_fF(dict(ra, adc="sar_sampled"), geometry(gd), 1.71) > 2.0
    tt = dict(cols=256, slices=2, n_adc=128, rail=dict(e_att_mac_J=1e-14), arr=dict(c_col_fF=56.0))
    assert dequant(dict(gd, f_merge=True), tt)["area_um2"] == 128 * 30.0 and dequant(dict(gd, rho_mode=None), tt)["e_J"] == 0
    assert abs(merge_cap_um2(dict(gd, f_merge=True, f_cu_lsb=0.25), tt) - 2 * 256 * 10.0 / 2.0) < 1e-9
    print("n5 self-check PASS", {kk: round(v, 1) for kk, v in ad["parts_db"].items()}, round(ad["snr_db"], 2))

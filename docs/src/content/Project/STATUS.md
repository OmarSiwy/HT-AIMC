A4 DONE: digital rail complete in scripts/digital/. RTL (9 modules + rail_top synth wrapper): nibble_combine (sat12 16x shift-add), slice_combine (sat14 x4), bacc_accum (param W, b_acc=20 per contract, tile_cnt port, saturating), abft_check (16+chk, 25b exact residual, programmable budget), requant (8b scale/5b shift/round-half-up/8b zero-point, sat INT8), sar_ctrl (4b SAR, 4-phase req/ack, 2FF sync on ack+result), event_ctrl (4b charge-balance count, early termination on no-cross, cap@15, Gray copy for CDC), sign_exit, tile_fsm (integrate/coarse/fine/readout, ReLU sign-early-exit skips whole conversion, coarse_en gates analog decisions so no orphaned req, ready-valid to fabric, Gray event-count export). Tests: 10/10 iverilog tbs PASS (self-checking, randomized vs independent tb reference; tb_rail integration incl. ABFT fault injection at T=1/2/4/8). Synth: yosys -> sky130_fd_sc_hd tt_025C_1v80: rail_top 3158 cells, 24712 um2, 9.1% seq, 0 check problems, no latches. Per-module cells: abft 1268, requant 1344, bacc 168, tile_fsm subtree 220 (event 57, sar 70, sign 1), nibble 49x2, slice 60. Port contract for A2/A3/A5 in scripts/digital/INTERFACES.md (handshake pacing >=2clk between reqs, quasi-static data rules, col_code = clamp(+-16*Nev+Dsar,127), Gray-restart caveat).
A1 DONE: library + sizing complete, all checks green. Tables: 8 real ngspice sweeps (sizing/tables/), max gm/ID 25.2-30.1 S/A (in 25-38 band), verified by sizing/test_tables.py (PASS). Fixed lookup.py invertible-branch selection: pfet L=0.15 has a VGS~0 leakage hump (apparent gm/ID 25.2) above its true subthreshold peak (15.5 at 0.63 V); branch now starts at the LAST local max, lookups clamp at 15.5 for that geometry. Sizing documented in sizing/SIZING.md: OTA (telescopic, in-pair (gm/ID=12, L=0.3) 0.91u, ncasc (10,0.3) 0.62u, pcasc/pmirr (10,0.5) 4.38u, tail (18,0.5) 11.76u, ID=10uA/side; measured: loop gain 330, settle 12.3/25.1 ns, SR 104 V/us, PASS); StrongARM (MVM sizes validated: offset <=2 mV, delay 0.48 ns, PASS); write switches (measured Ron: gc_write_n 5-64 kOhm over 0-0.9 V but 22.9 MOhm at 1.2 V -> WRITE-LEVEL CEILING 0.9 V for A3, series worst 90 k -> 8b settle 17 ns << 100 ns). tq_chain recalibrated: tq_cload 2.2p->550f (measured 40.5 ns/stage before, 10.15 ns/stage inner + 7.7 ns first stage now; tb_async_ctrl PASS incl. sequencing). Testbenches: tb_ota, tb_strongarm, tb_async_ctrl all ngspice-batch, numeric asserts, PASS. Imports for A2/A3 (PYTHONPATH=scripts): from library.pdk import NFET, PFET, VDD, mos, inv, nand2, nor2, include_models, lib_include; from library.ota import ota_spice, bias_spice, BIAS (ports: inp inn out vb_nc vb_pc vb_tail vdd vss); from library.cap_array import cap_array_spice; from library.cmos_switch import cmos_switch_spice; from components.strongarm.strongarm import generate (ports: vinp vinn outp outn clk vdd vss; vinp>vinn -> outp LOW); from components.async_ctrl.async_ctrl import generate, tq_chain_subckt (async_ctrl ports: go adc_done xbar_rst adc_go latch_out done vdd vss; tq_chain: in tap1..tap4 vdd vss, 10 ns/tap); from sizing import lookup (J_D/VGS/gm_gds/ft/W_for_gm); testbench helpers in library.testbenches.base (spice_prelude, run_ngspice, load_wrdata). Env caveat: flake dev shell unbuildable (schemify hash placeholder) — ngspice 43 pinned at build/ngspice43/bin/ngspice (auto-found by base.find_ngspice), python+numpy from a nix store env (e.g. /nix/store/ixcjbi65vkrg1id59px3snzkak7d1kpy-python3-3.13.13-env/bin/python3).
A5 DONE: compiler+golden complete. gguf_reader.py (existing, verified vs real smollm2-135m-q8_0.gguf: llama/30L/576d/9h/3kv/1536ffn/49152v, Q8_0+F32+F16+Q4_0 dequant, greedy tokenizer, fixture writer). scripts/golden/model.py rewritten to mirror A4 bit-exact (verified vs rtl/*.v): eventrate = evt-count sat15 + 4b SAR, mag=16*cnt+sar, col_code clamp +-127, n_eval=min(cnt+1,15); sat12/sat14(4*p_hi+p_lo)/20b-acc/requant sat8 8b-unsigned-scale shift0..24 offset-after-shift round-half-up; relu sign-exit = energy prediction + free fabric ReLU clamp (exact rule documented, single-row-tile only -> relu_en=0 for real model); ABFT residual now subtracts compile-known e.xq/D term (raw budgets 460-977 hid single-cap faults; corrected budgets 151-227 catch stuck-cap +8 at xq=127 with margin); float-safe conversion rounding for in-charge LoRA. compile.py: tiles REAL blk.0 head-0 (Wq/Wk/Wv 64x576, Wo 576x64) + FFN (gate/up 1536x576, down 576x1536) -> EXACT 10944 tile passes/token (576 attn + 10368 ffn), 9-token real prompt, bit-true forward THROUGH model.py (out finite, max 48, corr 0.985 vs float), emits manifest/digital_config/passes.json + programming/acts npz + golden_trace.npz + 11 representative real passes (worst|y12|=895, sparse, eterm min/max, chk_max, 1/matrix) as caps/params/pwm_lo/pwm_hi .spice + expected.json (emit_spice.py, documented in scripts/compiler/FORMATS.md). Early-termination measured on real weights: mean n_eval 1.36-1.73 of 15. Tests: test_golden.py 12/12 (quant roundtrips, PWM sums=|xq|*tq, mac identity, eventrate vs independent bit model incl sat/early-term, rails vs requant.v model, checksum linearity + fault trip, relu-exit rule, LoRA in-charge bound + SGD loss decrease, softmax KCL, kv decay, mvm accuracy) and test_compile.py 7/7 (reader vs real file, fixture roundtrip, tokenizer exact rejoin, vectorized==loop bit-true, pass counts, e2e real forward sane, emitted files self-consistent) — all print PASS via plain python.
A3 DONE: attention/memory analog set complete, all 4 tbs PASS. Components (scripts/components/): gain_cell_array (8x8 2T all-NMOS cells, 30f store, token=column write via row-shared wdata + per-column wsel, PWM row read via rd source lines 0.9V idle -> 0V pulse, cells SINK from 0.9V column rails; ports wdata0..7 wsel0..7 rd0..7 col0..7 vss); write_dac (4b binary in b0..3, R-string 15x10k 0..vref + 4:16 nand/nor decoder + tg tap mux); lora_sidecar (A[16]+B[16] gain cells, telescopic-OTA integrator C_int=1p on cola virtual ground, pfet ramp 2uA-design/3.4uA-meas V->T, OTA comparator + gate logic self-times B window, wide 100/0.15 rdb driver swinging vcm->0, embedded 2x write_dac update path). WRITE-LEVEL CHOICE per A1 constraint: NMOS-only cell switch, storage range capped 0..0.9V (write_dac vref=0.9, LSB 60mV); TG upgrade path documented in gain_cell_array docstring. Measured: gain cell store err -12..-30mV (injection, <1LSB), read current monotone 16/16 levels (7.3pA..6.35uA), tau_retention ~27ms (92.8uV droop/3.3us, 600x margin), non-destructive 10 reads=-43uV, write disturb -6.2uV, E_wr 7.5fJ/cell E_rd 2.4pJ/8-row pass; DAC 16/16 exact levels monotone, settle 4.6ns worst (spec 100ns), 1.2pJ/slot; softmax KCL checksum <=0.16% (spec 1%) all 3 temps x 3 patterns, per-branch rel err <=1.4% (spec 10%), beta 27.31/24.71/22.36 /V at 27/55/85C (drift -18.1% vs -16.2% ideal 1/T; I_b 0.58/1.18/2.2uA fixed-bias — PTAT bias is the production fix), settle 0.99us, 2.1uW static; sidecar outer product worst col err 1.36% pre-update, 0.93% post-update (spec 5%), eps=18ns V->T offset, E 7.1pJ/cell-write 67pJ/op. A6 INTERFACE: tie colb0..15 (B-cell drains) to tile column integrator virtual-ground (inn) nodes — sidecar sums IN CHARGE onto tile C_int; charges are baseline-differential (x=0 pass = per-column zero-point, matches A4 requant zero-point; re-zero after update writes); sidecar A-column current budget <=~10uA (class-A OTA limit) constrains A-level/x schedules; gain-cell col rails same 0.9V virtual-ground convention, same <=10uA note for simultaneous-row PWM; softmax input window: score spread <=~120mV about 0.6-0.85V CM for <10% ratio err (compiler maps scores; beta(T) above). Read-current I(V) is exponential-ish below Vth — compiler pre-distortion via the code->I calibration (tb_lora method: in-situ store sampling, I_cal to 0.1%).
A2 [1/5] rstring_ladder + tb_rstring PASS: 16 taps monotone exact (<0.01mV err, rails 0.55/1.35V), CDAC kickback recovery 3.4ns@R_SEG=200 (spec 5ns, 4x-wide tap TG; 1x write_tg was 12.2ns).
A2 [2/5] pwm_driver + tb_pwm_driver PASS: chopped-SC row drive (outa/outb = env gated by !phi2/!phi1), transfer count == code exact for 0..15 both signs, width linearity 0.26% dev (spec 2%), edges 0.25ns (spec 3.3ns), hi-window (16tq chop) exact. NOTE: PWM->charge realized as 2-phase SC transfer, 1 code unit = C_u*VDD/chop-cycle.
A2 [3/5] weight_tile + tb_weight_tile PASS: dump-at-connect SC banks + 500fF rail ballast. Linearity R2=0.999999 slope 99.1%, diff null +0.4 LSB, mirror 0.98%, real-worst cancelling column (32:32 units/cyc, = A5 pass max 34) -0.31 LSB; 64:64 synthetic -3.6 LSB = documented C_RAIL ceiling. Topology ladder measured+rejected in docstring (staggered phi2, hardwired-R, R+TG hybrids). read_caps() parses A5 caps.spice.
A5b [1/2] format registry + lowering law + K-quants: scripts/compiler/formats.py (FormatSpec registry int2..int8, fp2 {0,+-1} s+e1m0 ternary — the {0,+-.5,+-1,+-2} set needs 3b and is fp3_e2m0; fp3_e1m1/e2m0, fp4_e2m1=MXFP4, fp6_e2m3/e3m2, fp8_e4m3 OCP no-inf/448/top-code-NaN, fp8_e5m2 IEEE inf/nan, bf16/fp16/fp32; decode honors subnormals+specials, encode saturating, table-nearest <=8b / IEEE-cast wide). Lowering theorem: W ~ w_scale[j] * 2^exp[j,rt] * M, per-(row,16-input-block) BFP exponents aligned to row-tiles, b_eff=min(full-capture width, 8), M -> S=ceil((b_eff-1)/4) slices of 4b differential codes (sign free on C+/C-), sig 16^s in digital shift-add, exponents = per-column accumulator shifts (never analog). Acts: per-tensor scale + INT-b_x, ceil((b_x-1)/4) nibbles. Per-channel argmin-MSE scale grid fixes the coarse-format max-scale trap (fp2 0.7->3.3 dB). scripts/golden/model.py gains pwm_nibble_rounds/tile_mvm_general/mvm_lowered (existing fns untouched). gguf_reader: Q4_K/Q5_K/Q6_K dequant vs scalar ggml transcriptions.
A5b [2/2] compile integration + tests: compile.py --wfmt/--afmt/--target-bits (defaults run the FROZEN A5 path — whole out/ tree re-verified bit-identical vs pre-change snapshot; manifest/digital_config gain wfmt/afmt/slices/slice_sig/b_eff/b_x/sqnr_w_db as pure JSON additions); non-default -> run_formats() into out_formats/<wfmt>__<afmt>/ (lowering + D from all slice-x-window macs + requant + digital_config with slice sigs/exp_shift_span/required_acc_bits/abft:null(chk needs chk_shift=4 rail change) + passes.json by law passes/tile = ceil((b_w_eff-1)/4)*ceil(ceil((b_x-1)/4)/2), identity =1 -> 10944/token preserved, fp8 S=2 -> 21888 + manifest per-tensor wSQNR/xSQNR/mvmSQNR + over_by8 flag). test_formats.py 9/9 PASS: registry round-trip/monotonicity/extremes all formats, e5m2 inf/nan + e4m3 448/NaN + subnormal policy explicit, pass law, int4/int8 identity (quant fns + compile_matrix fields + MVM bit-equal), REAL Wq head-0 format matrix vs float64 with pinned floors (int4x int8 20.8 dB, int8 19.1, fp2xfp3 3.3, fp4 16.6, fp6 17.3, e4m3xe5m2 24.6, fp16/fp32/bf16 24.5-24.7 = the B_y=8 CSNR ceiling, flagged over_by8; floors = measured-2dB), multi-nibble b_x=12 rounds, K-quants, existing test_golden 12/12 + test_compile 7/7 re-run green. FORMATS.md documents registry/law/ceiling/floors.
A7 FIX1 charge-scale calibration: converter refs never sat on the tile's actual charge/unit. Measured Q_UNIT = 267.45 aC/code-unit (tb_weight_tile single-crosspoint method, slope 13.3726 mV/code @ nibble 10 on C_int 200 fF) = 99.06% of ideal C_U*VDD. New named constants Q_UNIT/K_CAL in integrator_conv.py: C_pkt = 16*D*C_U*K_CAL (C_pkt*VDD = 16*Q_UNIT, 1 packet = 16 code units exactly); U_CAL = K_CAL*U1 rescales all thr/sar ladder spans (_conv_common.U_CAL, analogioc_top.U1, tb_integrator_conv/tb_tile_mvm/tb_ffn_e2e/tb_training_step). Verified: 1-row code-15 column -> code 16 (+-1 OK), mac 32 -> code 32 exact.
A7 FIX2 early-termination wiring: comparator strobes were already done-gated (ck1), but the packet bank chop was gated only by go — early-done columns kept chopping through the rest of the shared assembly coarse schedule (residue corruption pre-SAR + idle burn). New run_c = go & !done gates the bank TG phi buffers AND the packet pwm_driver phis (driver idle chop alone = 0.38 pJ/conversion from vdd_pkt, measured). Verified: code-0 conversion = 2 strobes, E_conv 0.50 pJ (was 0.99); fine phase 0.27 pJ (was 0.50).
A7 FIX3 timeouts: TimeoutExpired killed ffn/training D=2 windows at 3000 s. run_spice timeouts -> 9000 s (harness.py default, tb_tile_mvm.run_window, tb_training_step.train_pass). Sim schedules/probe lists audited — already tight; FIX2's frozen packet chop also cuts per-window event churn.
A7 DONE: fixes + rerun launched (PID 1702776, nohup ./rerun_failed.sh > rerun.log; results append to RESULTS2.md).
A8 [1/n] DIAGNOSIS (no-sim + short sims): tb_tile_mvm hi-window failure is a code-INDEPENDENT per-column NEGATIVE offset, err ~ -(4 + 1.2*n_banks) LSB — corr(err_hi, n_banks) = -0.78 (pass_00) / -0.85 (pass_05) from the existing FAIL log vs caps.spice bank counts; lo-window errors are the same mechanism at ~1/8 scale (window 165 ns vs 1285 ns). Mechanism class: per-bank rail leak over the 16x-longer phi2 connects + a converter-own floor — NOT 17-column droop (supplies/vcm are ideal sources in tile mode; column-count sweep 2/8/17 in flight to confirm, diag_a8.py).
A8 [2/n] MECHANISM ISOLATED (diag_a8.py, 6 short sims + probe rerun): NOT droop (2-col vs 8-col hi errors identical: +5/+5, zero-col +1/+2), NOT in-window injection (probe: out0 = mac+0.6u at hi-window end, i.e. integration exact). Error accrues in the CONVERSION phase: at t_win the chop switches 16TQ->TQ and the tile banks re-equilibrate to the TQ limit cycle, dripping for 100+ cycles (tb_weight_tile's sign-flipping drip: +6.4 aC/bank/cyc @1 bank, -4.3 @16 — explains single-bank diag +4.5 LSB AND real-pass -15 avg at ~10 banks/col, corr -0.78/-0.85). Offset is code/envelope/weight-INDEPENDENT (nib 1 vs 7, w 2 vs 15: same +4..5) and additive through the coarse+fine assembly (over/under-fires self-correct via fine). Lo window: banks already in the TQ limit cycle -> only the small residual drip (+-2..4).
A8 [3/n] FIX (priority-1 zero-point, no component changes): x=0 calibration window per programmed tile / window type / cmax schedule (measure_baseline + zero_pwm in tb_tile_mvm, cached), subtracted per column before golden + ABFT — the A3/A4 y=code(x)-code(0) convention tb_training_step already uses. Wired: tb_tile_mvm.check_pass (also serves tb_ffn_e2e chip mode), tb_audit (clean-tile baseline for both runs; a stuck cap moves no charge at x=0).
A8 [4/n] VERIFICATION RESTART: first verification wave (pass_00 windows + tb_integrator_conv regression) collided with the A7 rerun's chip-mode ffn windows — kernel OOM-killed ngspices on both sides and the A7 rerun (PID 1702776) died mid-tb_ffn_e2e (RESULTS2.md: integrator_conv PASS, eventrate PASS, tile_mvm/audit FAIL = pre-fix expected). Machine idle-verified, relaunched: rerun2.sh (PID 1878814 -> RESULTS3.md: tb_tile_mvm full, tb_audit, tb_ffn_e2e, tb_training_step, metrics — all now on the zero-point path) + tb_integrator_conv/tb_eventrate regression chain (PID 1878815), sequenced to stay under the 31 GB ceiling (max 2 concurrent windows + small single-conv sims).
A8b GATE1 tb_integrator_conv regression PASS: all 5 mac points within +-1 LSB (worst 1), E(0)=0.50 pJ vs E(165)=5.10 pJ (ratio 0.10, early-term intact). Orphaned A8 ngspice sims (2x pass_00 zlo/zhi, tb_ic_mn50, 2x pass_09) killed before rerun.
A8 [5/n] REGRESSION GATES GREEN (post-fix, components untouched): tb_integrator_conv PASS (5 mac points all +-1 LSB), tb_eventrate PASS (E monotone + early-term), single-column mac 32 -> code 32 EXACT (A7 gate held). rerun2.sh running the calibrated acceptance set.
A8 [6/n] ROOT CAUSE FINAL + FIX v2 (tile clock gate): diag_a8b transient probe (16-idle-bank column, hi window, 1.5 us TQ tail, no conversion) shows the tile-bank idle-chop drip NEVER settles (-0.35u/cycle perpetual at 16 banks, +35u rate-switch transient, nonmonotonic) — decisions ride a moving, x-history-dependent value, so zero-point subtraction alone left +-9..15 residuals (fresh pass_00 z-runs vs x-runs: baseline captures the bulk — hi base +4..+24 tracks bank count — but sign-latch/fine-clamp nonlinearities on the moving value do not subtract). FIX: gate the TILE phis outside the integration window (tphi1/tphi1e/tphi2 tile-side clocks, chop during window only, park in phi1 clamp = analogioc power-up rest state) — the same disease+cure A7 applied to the converter's packet bank (run_c); silicon = tile_fsm INTEGRATE-phase clock gate. Touched: tb_tile_mvm.tile_phi_sources/run_window, analogioc_top (tile on tphi pins, STIM/MVM_DRIVEN/park), tb_training_step.train_pass (drives tphi; also cleans the sidecar ramp phase). x=0 baseline kept (captures the remaining converter-floor offset). weight_tile/int_conv components UNTOUCHED.
O1 SPECS: scripts/specs.py landed — single executable design-math module: every derived spec (OTA sizing chain via gm/ID tables, kick filter R-C, tau_absorb, coarse cadence, r_seg/c_tap, C_int/C_u laws, t_q floor, conversion/pass timing, pass energy, tok/s / tok/J) is a function of the active PDKConfig; raw params added to base.py+sky130.py (r_sq_wire 0.125, wire_pitch 0.34, a_vt 5, ss 90, MiM 2fF/um2, 9.2 ps/fF measured inv slope, jitter 200ps); measured cal knobs (K_CAL 0.9906, beta_int 0.22, c_ota_self 311f@10uA) in specs._CAL per PDK. Self-check PASS (asserts pdk.sizing == ota() output, cadence 60ns, r_seg 8k, c_tap 29p). integrator_conv/rstring_ladder/_conv_common/tb_ota/tb_tile_mvm/tb_integrator_conv/metrics.report all import from specs — no hardcoded copies of the changed constants remain in O1-touched files.
O1 ITEM1 LANDED coarse cadence 80->60 ns (specs.coarse_cadence = 2*tau_absorb snapped UP to the 10ns chop grid; 54ns ideal is off-grid — packet fires must land in the chop all-off gap). Falsifier PASS (pre-rebias isolation run): tb_integrator_conv 5 mac points worst |err| 1 LSB, E(0)/E(165) = 0.10, n_eval exact on all points.
O1 ITEM2 LANDED r-string R_SEG 200 -> 8k (specs.r_seg static-power budget; 200 ohm burned 213uW/string worst-band) + 29pF/tap decap (specs.c_tap = C_kick*V_kick/(tol/2)) + tap TG 8x. Falsifier PASS: 16 taps monotone (worst err 0.21mV), kick held: tap outside 0.5mV band only 3.51ns < 5ns (absolute-band criterion replaces relative recovery: with the high-R string the decap holds instead of recovering). CAVEATS: took 3 sizing iterations (15p/tg6 hovered at band edge -> 2x margin); decap area 232k um2/ladder if ALL taps decapped — silicon only needs the trim taps actually used (converter duty uses end taps = the rails).
O1 ITEM3 LANDED OTA re-bias 10->6 uA/side (specs.I_SIDE, constant-J width scaling through specs.ota() -> sky130 pdk.sizing: in 0.54u, ncasc 0.37u, pcasc/pmirr 2.63u, tail 7.06u; BIAS voltages J-invariant). Falsifier PASS: tb_ota 50mV-step settle 21.9 ns < cadence/2 = 30 ns, loop gain 483 (>200), SR 57 V/us, tail 8.2 uA; tb_integrator_conv point mac +16 -> code 16 EXACT (E_coarse 0.64 pJ). OTA static 612 -> 367 uW (17 cols); tau_absorb 30 ns keeps the 60 ns cadence on-grid (specs self-check asserts the chain).
O2 PDK PROJECTIONS: library/pdks/asap7_proj.py + tsmc_n4_proj.py landed (projection-grade PDKConfig sets, every raw param sourced+confidence-labeled, NOT registered as active PDKs, no SPICE; additive fields cal_proj/t_q_grid/topology_flags — 0.7/0.75V breaks the 5-stack telescopic -> two-stage/ring-amp flag, fin quantization flag). scripts/metrics/pdk_projections.py evaluates specs.py per PDK -> scripts/metrics/PDK_PROJECTIONS.md (sky130 anchor asserted: tau 30ns/cadence 60ns; specs.py untouched). Headline (squeezes S4/S5/S6): asap7 tau 4.6ns/cadence 9.2ns/conv 193ns/pass 212ns/21pJ; N4 4.3ns/8.7ns/182ns/200ns/23pJ. Findings from the formulas: C_int re-derives to 52fF at both advanced nodes (kT/C law binds, not layout); t_q floor flips from jitter (sky 200ps) to row RC (~85-90ps); pass stays conversion-bound everywhere (conv/window ~13x); tau_absorb becomes C_FILT_MIN(60f)-floored. vs Etched Sohu (vendor 62.5k tok/s/die, 35-60 tok/J): tok/J WON at 70B — asap7 175 / N4 161 tok/J = 3-5x margin (projected); tok/s/die LOST on cadence alone (N4 7B best 8.5k = 13.6%); crossover needs conversion amortization K>=13 windows/conv (paper law:wrapper, K*=64) -> 122k tok/s/die at 7B = 2x Sohu; 70B needs ~6 dies. O1b hooks noted in PDK_PROJECTIONS.md: TQ_SIM/sar_time/T_ACQ constants -> per-PDK derivation, _CAL -> PDKConfig field, pass_energy_pj pass-time arg, V_SWING/MAC_MAX/ladder-kick constants sky-anchored, C_FILT_MIN scaling law, per-PDK gm/ID tables (fin-quantized).
O1b DEBT (O2 specs.py refinement list, deferred — mechanical, no falsifier risk): (1) TQ_SIM should derive from max(t_q_floor, jitter_budget) per PDK; (2) sar_time/T_ACQ/T_TRIAL/T_SAR_TAIL should scale with tau_absorb (5ns literal in sar_time unreachable off-sky130); (3) K_CAL -> PDKConfig field (currently specs._CAL keyed by pdk.name — works, just not a config field); (5) ladder-kick constants C_KICK_CDAC/V_KICK/band are sky130-anchored, parameterize for per-PDK r_seg/c_tap; (6) C_FILT_MIN needs a CDAC scaling law. Item (4) pass-time argument to pass_energy_pj LANDED this pass. NEXT-ITERATION TOP ITEM (O2, do first): conversion amortization K>=13 — the paper's K* super-tile cascade (share one conversion across K accumulated tile windows; mini is K=1). Dominant remaining tok/s lever, ~14x on the binding constraint at fast nodes (metrics/PDK_PROJECTIONS.md). Not implemented in this pass by coordinator instruction.
(analog attention-engine entry removed 2026-10-04: dropped from scope)
(analog LUT study entry removed 2026-10-04: study dropped with the attention engine)

DPS+LATTICE DONE (A5, scripts/compiler/ + scripts/golden/): (B) DPS rank-48 root-caused honestly and test_dps now GREEN encoding TRUE behavior. The +7.52 dB tax is NOT a bug: the scheme is exact in integer arithmetic (measured algorithm tax -0.02 dB on real attn_q, matching the paper's +0.13 dB claim), but folded A-side combos are sums of up to 16 INT4 weights (|A| reaches ~35, ~7 bits) and forcing them into one 4b differential cap slice needs a provably-minimal per-product shift s_a (plus s_b on the B-side) that throws away ~2 bits -> +4.69..+10.93 dB across the 7 real matrices. Recovering it needs a 2nd slice = 2*48/64 = 1.5x passes, erasing the 0.75x tile win. VERDICT: DPS-48 is NET-NEGATIVE at INT4xINT8 cap quantization -- kept flag-gated OFF as a documented dead-end-at-this-precision (may turn positive at fp8/higher b_x where S=2 is already baseline). test_dps asserts algorithm-tax<=0.5 dB AND INT4-tax>=3 dB (the real hardware penalty); FORMATS.md 'DPS-48 verdict' table. (C) --lattice CSNR mid-lattice thresholds (law:csnr/L6): golden output_lattice/lattice_thresholds/convert_lattice/convert_uniform/csnr_db (additive; existing fns untouched, default out/ bit-identical -- 10944 passes/token, deterministic). scripts/compiler/lattice.py emits per-tensor tap-code threshold schedule (out_lattice/threshold_schedule.json, 4b R-string taps tap_k=vrn+k*(vrp-vrn)/15, code-unit->volt via vcm+c*u) + measured csnr_gain.json. Measured: controlled sparse col (pitch 3) +inf dB at pitch/sigma 7.5 dying to +0.17 dB at 0.5; dense lattice ~0 dB (mid==uniform, death regime) = paper's law reproduced. Real matrices peak +15.8..+25.7 dB in low-noise regime, decaying slowly with sigma_a (sparse achievable set over wide extent). SPICE wiring out of scope; A3 converter handoff documented in FORMATS.md 'lattice thresholds'. test_lattice.py 4/4 PASS. Baselines re-verified: golden 12/12, formats 9/9, compile 7/7, dps + lattice all green.

CASCADE ACCURACY ROOT-CAUSED (analog/testbenches/diag_cascade_gain.py, single-column A/B probe of the column integrator node v(out0), confirmed full 17-col): the tb_cascade ~0.88x (12% low, K-INDEPENDENT) accuracy FAIL is NOT a cascade bug — cascade-c1 reduces to the proven "lo" window BIT-FOR-BIT (identical v(out0) and code on every real pass_05 column), so the error is ALREADY in the base "lo" MVM and cascade inherits it unchanged (hence K-independent). The deficit is on the RAW integrator node: v(out0) reads ~0.84x of ideal charge (col 0 mac57 +64.02/76.22 mV -> code 51; col 8 mac80 21 banks -> 70; col 6 mac16 -> 13) — a TILE multi-bank charge-transfer loss, not conversion/zero-point (zero-point only -1..-2 LSB). ROOT CAUSE: the weight_tile "divides out" assumption + A7 K_CAL (Q_UNIT 99.06%, measured single-crosspoint) hold for ONE bank (synthetic 1-bank control here: mac60 -> code60 EXACT, gain 1.000x; tb_integrator_conv/A7 mac32->32 also single-bank) but a real column dumps 11-21 mixed-sign banks onto the shared rail+500fF C_RAIL each phi2 and delivers only ~84% to C_int (finite OTA gain/settle, worsens with bank count). OUT OF SCOPE for a cascade-branch fix (needs base-tile recalibration / bank-count-aware K_CAL, touching PROVEN components); tracked against A7/weight_tile, NOT cascade. STRUCTURE amortization (E/pass 0.55x/0.41x, chain 0.49x/0.31x) stays PASS; specs K=1 anchor 4.12us/22.2 tok/s holds; diag_pingpong re-verified green post-migration, cap-A/cap-B crosstalk floor +1/-3 LSB raw, 0 after zero-point (single-bank, no multi-bank deficit).

A9 MULTI-BANK CHARGE FIX (per-column reference correction, PARTIAL — honest): added specs.multibank_efficiency(n_banks) (eff(1)=1.0 A7 anchor, saturating-exp to 0.84 floor, measured diag_multibank) and scaled each converter column's U_CAL span + coarse packet cap (integrator_conv pkt_scale) by eff(n_banks[col]) in tb_tile_mvm.run_window (per-column ideal reference rails col_rails) + analogioc_top (chip mode, mb_correct opt-in for tb_ffn_e2e); PHASE 1 (diag_multibank): efficiency vs n_banks 1.0->~0.91 monotone, linearity spread 0.007 over mac 15-70 => pure gain IN THAT RANGE. PHASE 3 HONEST: single-bank anchor held (tb_integrator_conv worst |err|2 = IDENTICAL to a HEAD/pre-A9 worktree baseline, a PRE-EXISTING mac+15 fine-SAR edge, NOT an A9 regression; specs self-check K=1 4.12us/22.2 tok/s + energy unmoved), but the per-column SCALAR correction does NOT restore +-1 LSB universally — validate on real pass_00 cols: col1(19u,code-48)->0 err EXACT, col3(21u,code111)->+4, col8(23u,code-127)->+3. Root-caused (raw-eff probe): efficiency is per-column CELL-PATTERN dependent not n_banks (0.835/0.878/0.899 at 19-23 units vs the fit's 0.84) PLUS a high-code coarse-loop INL (col3 eff matches fit yet still +4 at |code|111). Achievable: +-1 LSB for |code|<~60, +3/+4 residual for |code|>~110 (down from -12..-19 LSB pre-fix, ~4-5x). Full +-1 LSB needs a per-column MEASURED gain (known-input cal / ABFT servo test_gain_servo) in place of the formula; the INL residual then bounds it. Full 17-col tb_tile_mvm not run to completion (~2-3h/pass on this grid); the 1-col corrected validation is the definitive check. METRICS.md unchanged (no code-level accuracy claims there; energy/tok-s unmoved).

HETEROGENEOUS PER-TENSOR K (scripts/compiler/, projected): scripts/compiler/metrics/perlayer_k.py + test_perlayer_k.py + CASCADE.md "Heterogeneous per-tensor K" row. Reuses specs.k_star/cascade_snr_db/conv_time (physics NOT reimplemented); pulls per-tensor pass counts + classes from scripts/compiler/out/manifest.json (576 attn + 10368 ffn = 10944/token, counted). Per-class SNR budget (STATUS anchors, documented): shared SNRt=28 dB; per-stage analog CSNR SNRs=34 dB attn / 38 dB FFN (FFN's larger accumulation reaches higher source SNR; attention 34/28 reproduces specs' K*=4 anchor). K_layer = budget FLOOR (largest K with cascade_snr_db(K,SNRs)>=28, which includes the (1+eg)^K gain term). SCHEDULE: attention K=3 (random-bound), FFN K=7 (GAIN-term-bound: ln(1.02)/eg=6.6, not the random 10.0), conversion-weighted avg K=6.54, emitted to scripts/compiler/out/perlayer_k_schedule.json. AGGREGATE (merged-window S5 + pingpong S6 + cascade pass(K)=max(136*t_q,T_conv/K)+4*t_q; token time=sum passes_tensor*pass(K_tensor)): N4/7B = 60.3k tok/s/die = 0.97x Sohu 62.5k = 1.63x uniform-K4 (37.1k), bracketed [uniform-K4, uniform-K14=121.9k] as asserted. HONEST CEILING: per-tensor K reaches ~PARITY, NOT 2x — FFN K capped at 7 by the gain-compounding term (cascade_snr<28 dB at K=8), so 2x is now a SERVO-eg problem (eg 0.3%->0.15% ~doubles the gain-K cap toward K=13) not an SNR-allocation one. Attention is only 5% of passes so its shallow K barely moves the aggregate. 70B: 6.0k/die -> ~11 dies for Sohu parity (density, not K, is the 70B lever). Test asserts: (1) every K respects cascade_snr_db(K)>=SNRt AND is the floor, (2) FFN K > attn K, (3) het tok/s in [uniform-K4, uniform-K14] at every PDK/scale. Baselines re-verified GREEN (golden 12/12, formats 9/9, compile 7/7); default out/ path bit-identical (only NEW files added, no default-path code touched).

TASK A DONE — mac+15 fine-SAR edge FIXED (analog/testbenches/diag_fine15.py). ROOT CAUSE: during the fine SAR acq the CDAC sampling load connects to the OTA output and the O1 6uA OTA (10->6uA re-bias) droops the residue ~0.80x (22.74->18.5 mV, mac15) — a STEADY-STATE loop droop (asymptotes low, NOT a settle transient: +60/120/200ns extra settle only reached fine 14, non-monotone; reducing the CDAC 7.5->5.0/3.75f did NOT help and hurt LSBs -> the load is OTA-drive-limited, not cap-settling; vref stiff, no reservoir sag). FIX (reference recalibration, same class as A7 U_CAL): specs._CAL fine_ref_trim=0.80 shrinks ONLY the fine SAR full-scale (sar_p/sar_n span) so the drooped residue crosses the right fine thresholds; coarse thr untouched -> fine=0 codes (mac16 boundary, mac32 A7 anchor) UNMOVED. Landed in specs.fine_ref_trim + _conv_common.FINE_REF_TRIM -> tb_integrator_conv.ladders (UDF), tb_tile_mvm.ref_table/col_rails/col_rail_srcs, analogioc_top.rail_sources. RESULT: tb_integrator_conv OVERALL PASS, all 5 points +-1 (mac+15 -> 15 EXACT was +13; +0/+16/+165 exact, -50 -> -51 no regression), worst |err| 1 (was 2), early-term intact E(0)/E(165)=0.10, E_fine 0.27pJ unchanged -> conversion time/energy + K=1 anchor 4.12us/22.2 tok/s UNMOVED (reference span is a voltage, not charge). specs self-check PASS (pass_time 4.12us). integrator_conv component byte-identical (git no-diff); scripts/golden/compiler/digital untouched.

TASK B — high-|code| coarse-loop INL: measured gain + fine-trim CLOSES in-range, over-range/high-count IRREDUCIBLE (GATED-STOP, no 2-3h sweep). With Task A fine-trim + A10 measured per-window gain, cheap per-column pass_00: col1(-48)->0 EXACT, col3(+111, IN-RANGE near-full)->0 EXACT (A9 was +4 — the in-contract high-code deficit is CLOSED), col8(-143, OVER-RANGE past +-127 clamp)->+3. B1 packet-count INL sweep (synth 21-unit column, measured gain, lo_mac 45/81/117/135 = count 2/5/7/8): err -1/+1/-2/+2 — INL GROWS with packet count and is GAIN-INDEPENDENT (col8 gain-sweep: 0.80 still reads -124, a plateau; reference scaling cannot cross the +-1 neighborhood). ROOT CAUSE: the coarse packet is one SC bank (Cpk dump-at-connect onto vg, integrator_conv.py) with a per-fire transfer error that accumulates over count; the eff-scaled reference scales packet charge AND thr threshold by the SAME factor so the crossing count is scale-invariant -> a single scalar gain can't linearize a count-dependent alternating INL. IRREDUCIBLE in scope: fixes are per-count digital (event_ctrl.v, digital/ NOT ours), packet-charge topology (moves coarse energy/time), or a code-shifting fixed decouple — none an analog reference/loop-cal knob. ENVELOPE: typical real passes (05-09 attn q/k/v/o + ffn_gate) have ZERO over-clamp cols, |code| max 76-117 all IN-CONTRACT -> +-1 LSB; torture passes (00/03/04/10) carry over-clamp cols (|mac| to 911 railing to +-127) that miss by +2/+3 and are OUTSIDE the +-4-sigma CODE_MAX=120 contract. B2 GATE = STOP per instruction (col8 over-range + synth count-7 not +-1, irreducible without topology): the full 2-3h 17-col tb_tile_mvm was NOT run — cheap single-column probes (1-col==17-col) already establish the known-partial. Net vs A9: in-range near-full col3 +4 -> EXACT. Default path byte-identical (analog/* only: specs/analogioc_top/_conv_common/tb_integrator_conv/tb_tile_mvm; scripts/golden/compiler/digital untouched); energy/tok-s/K=1 anchor unmoved (measured-gain + fine-trim are reference-cal, not charge/topology); METRICS.md unchanged (no code-level result moved).

SERVO-EG ACHIEVABLE + 2x VERDICT (task #21, compiler math + committed measured data, NO SPICE): docs/src/content/Project/SERVO_EG.md + additive perlayer_k.eg_sweep (default avg-K=6.54 / 60,328 anchor + schedule JSON BYTE-IDENTICAL, verified). ACHIEVABLE eg from three routes: (a) measured-gain residual (A10/A11) backed out of in-contract +-1 LSB = 1/|code| -> ~0.83-0.90% at full scale (bulk bound, not a converged servo number); (b) ABFT servo test_gain_servo (run read-only, PASS) converges to eg 0.196-0.203% typical / 0.437% worst-seed (this is what EG_SERVO=0.30% anchors); (c) PELGROM UNCORRELATED per-cell floor a servo CANNOT remove (b_eff=-log2(sigma_r)-1.79): unit-cap mismatch sigma_C/C=A_C/sqrt(area) at C_u=0.15/0.10/0.09 fF gives per-cell 5.5/6.7/9.4% -> eg_floor (sigma/sqrt16) ~1.37% sky130 / 1.68% asap7 / 2.34% N4 -> the floor SITS ABOVE 0.15% by ~10x, so 0.15% is a CELL-AREA/matching target, NOT a servo one (servo removes correlated column-mean gain; uncorrelated cell scatter is floored by matching). eg->tok/s CURVE (N4/7B, perlayer schedule): eg 0.30%->0.97x(60.3k), 0.20%->1.08x(67.7k), 0.15%->1.08x, 0.10%->1.20x(74.8k), eg->0 SATURATES at ~1.20x (FFN K=9). CRUX (kills the servo-alone story): cascade_snr_db carries BOTH terms and at FFN SNRs=38 dB the RANDOM sqrt(K) term caps FFN at K=9-10 with eg=0 -> tightening the servo moves FFN only 7->9, NOT to 13-14; the 1.95x/K=14 ceiling is a UNIFORM-K=14 needing SNRs>=44 dB, not reachable by servo. VERDICT: 2x-Sohu is NOT reachable by tightening the servo (tops at ~1.20x, and the required eg is below the Pelgrom floor anyway). The REAL unlock is the PARALLEL charge-summing super-tile (CASCADE.md note + test_gain_servo assert #4): one g per column on the CHARGE SUM -> gain error K-INDEPENDENT (measured flat 0.437% at K=1/4/13), so (1+eg)^K VANISHES from cascade_snr, lifting FFN to the random-bound K=10 for FREE (no servo tightening) at the cost of INT8 partial sums on the digital fabric; going past K=10 to the 1.95x ceiling additionally needs the random SNRs relaxed (deeper analog accumulation / finer converter). So 2x = parallel super-tile + higher SNRs, NOT servo alone; the series-chain (1+eg)^K the projection uses is the pessimistic topology. Compiler suites green (default perlayer_k output bit-identical; only NEW file SERVO_EG.md + additive eg_sweep function; specs/golden/analog-code/digital untouched).

TASK #23 COARSE-LOOP INL ROOT-CAUSED — it is a FINE-SAR + gain-interaction OPERATING-POINT INL, NOT a per-count packet drift; NO single-variable digital LUT (per-count OR per-fine) can linearize it (analog/testbenches/diag_countinl.py, sole-driver cheap 1-col sweeps). Characterization err(N): (1) UNCORRECTED real pass_05 lo columns carry a LARGE multi-bank charge deficit — col13 mac-89 reads -73 (err +16 low), so the A10 measured gain is MANDATORY and removes the bulk. (2) POST-GAIN residual on a FIXED synth column, swept across count boundaries: err 0/0/+1/-2/0/0/-2/0/0/+1 at count 1..8 — NOT monotone in N, NOT a repeatable f(N) (N=4/6/7 read 0 while N=3/5 read -2; the discriminator is the FINE residue, not the count). CASCADE.md Task B "count-dependent" was a confound: the B1 sweep varied q, moving count AND fine together. (3) FINE-ISOLATION sweep (3-unit col, count~0-2, fine 0->15, gain~1): the converter reads UNIFORMLY HIGH +1..+3 LSB, a fine-SAR positive DNL humped at mid-fine (fine~8 -> +2/+3), fine 0/15 -> ~0. This +1 mid-range bias persists WITH the shipping A11 fine_ref_trim=0.80 already applied (a scalar trim cannot flatten a hump). ROOT CAUSE: the 4b charge-redistribution fine SAR has a mid-code positive DNL (~+1 LSB, +2/+3 at fine~8); on real multi-bank mixed-sign columns this ENTANGLES with the per-column gain over/under-correction, so at a GIVEN (count,fine) readout the residual can be +2 OR -2 depending on the column's gain (pass_05 in-contract: col1 +2 / col2 -2 / col7hi -3 / col13 -3, all different sign at similar operating points). Because the error sign is set by an un-observable-at-readout quantity (the column's charge deficit vs its applied gain), NO readout-indexed LUT (count or fine) inverts it -> the per-count DIGITAL correction the task hypothesized is the WRONG TOOL and was NOT implemented (would add a golden+RTL LUT that does not close +-1). LOCUS DECISION (reported to coordinator): NO digital-domain change made; scripts/golden/compiler/digital UNTOUCHED, default path byte-identical, A7/A8/A11 anchors unmoved, energy/K=1 anchor unmoved. Only analog/testbenches/diag_countinl.py added (characterizer). ACHIEVABLE ENVELOPE: with A10 gain + A11 fine-trim, typical in-contract codes are +-1..+-3 (bulk closed from the raw ~+16 deficit); the residual +-2/+3 on ordinary mid/high in-contract codes (RESULTS3 pass_05 col13 -3) is the fine-SAR-DNL x gain-interaction INL and is IRREDUCIBLE by reference-cal or a 1-D digital LUT. TWO legitimate closers, both out of the reference/LUT scope: (a) reduce the fine-SAR DNL itself (a 5th SAR redundancy bit / larger CDAC unit + per-code cal, an analog TOPOLOGY change that moves fine energy/time and the K=1 anchor), or (b) the #22 PARALLEL charge-summing super-tile — the coarse loop then sees ONE clean charge sum with ONE per-column gain (no mixed-sign multi-bank deficit to over-correct), removing the gain-interaction that flips the residual sign. #22 remains the real correctness fix, now for the RIGHT reason (kills the gain-interaction, not a count drift).

(analog attention-engine entry removed 2026-10-04: dropped from scope)

TASK #24 ERROR-IMPACT (model-level, no SPICE): the measured in-contract +-3 LSB tile-MVM residual (RESULTS3 pass_05, col13 -3) is TRANSPARENT to the model — injected on y12 through the REAL blk.0 forward (9-token prompt), +-3 gives blk.0 cos 0.9973 / softmax-L1 0.014 / 100% proxy next-token argmax agreement; the model-tolerable budget is +-8 LSB (100% argmax, cos>0.99), first break at +-16 (88%), so measured +-3 sits ~5x inside spec. VERDICT: the +-1 LSB acceptance gate is a converter-ENOB target, not a model requirement — RELAX it to the model-tolerable +-8 LSB; the #22/SAR topology fix is NOT required for correctness (still wanted for tok/s). ABFT stays in budget at +-3 (62/199) so fault detection is unaffected. NEW FILES ONLY: docs/src/content/Project/ERROR_IMPACT.md + scripts/compiler/test_error_impact.py + opt-in golden.model.TILE_ERR (default None -> default path byte-identical, test_golden 11/11 + test_compile 7/7 green).

(analog attention-engine entry removed 2026-10-04: dropped from scope)

(analog attention-engine entry removed 2026-10-04: dropped from scope)

(analog attention-engine entry removed 2026-10-04: dropped from scope)


(analog attention-engine entry removed 2026-10-04: dropped from scope)

(analog attention-engine entry removed 2026-10-04: dropped from scope)

TASK #17 ADAPTIVE-RANGE CONVERTER — CHARACTERIZED, VERDICT: ALREADY-CAPTURED-BY-EARLY-TERM (small remainder, NOT the 27h2 4.5x). The concept: adapt the coarse packet charge Delta_c per-column to |partial-sum| so sparse columns fire fewer packets. QUANTIFIED HONESTLY on the REAL SmolLM2-135M workload (compiler out/passes/pass_*typ_* = attn q/k/v/o + ffn gate/up, 192 columns) against the EXISTING early-termination. Deliverables (additive, default byte-identical, no analog circuit change): specs.adaptive_range_saving(coarse_packets, r) — additive model keyed to the MEASURED out/tile_energy.json e_vs_code points (E_coarse=0.204pJ floor + 0.559pJ/packet; fine/SAR FLAT 0.274pJ, code-independent) — plus analog/testbenches/tb_adaptive_range.py (rolls the model over the compiler's per-column packet counts; asserts a/b/c + the whole-pass verdict; OVERALL PASS). FINDINGS: (1) THE OPPORTUNITY IS MOSTLY GONE. Early-term already fires 0 coarse packets on 52% of columns (|code|<16 -> pure floor: measured code0 0.204pJ == code15 0.206pJ) and mean packets/col is only 1.11. Adaptive range only bites on the 29% of columns with >=2 packets. (2) 27h2's 4.5x is vs a FIXED-RANGE NON-EARLY-TERM baseline and it is a Delta-RELAXATION (accuracy give-up) number, NOT a same-accuracy range saving — the note's own algebra (E=k1 log(VDD/Delta)+k2(VDD/Delta)^2) proves range adaptation at fixed absolute accuracy buys NOTHING; only relaxing the LSB or skipping conversions pays, and the integrating coarse loop's early-term IS the skip. (3) INCREMENTAL OVER EARLY-TERM: at r=2 (Delta_c 2x coarser, packets halved, but the 4b SAR must grow to 5b to absorb the coarser residue) = 19.9% of DYNAMIC E_conv; r=4 (6b SAR) = 29.4%. (4) BUT WHOLE-PASS IT IS ~0%: pass energy is 83% OTA static burn (1513/1813 pJ), set by conversion TIME which adaptive range does NOT shorten; conv-dynamic is 10% and packets ~57% of that. Adaptive-range 2x saves 3.7 pJ/pass = 0.2% of pass energy = 0.2% tok/J. HONEST VERDICT: NOT worth an analog Delta_c circuit (would need a 5-6b SAR redesign + per-column magnitude pre-sense for a 0.2% whole-pass gain — textbook over-engineering; the SAR-absorb constraint blocks the free lunch, and the LSB-relaxation that WOULD pay is a per-tensor SNR give-up already owned by the cascade-K knob). The real converter-energy lever is cascade K (shortens conversion TIME -> cuts the 83% static: measured tok/J x1.47/x1.93/x2.28 at K=2/4/8, specs self-check). Adaptive-RANGE is a ~0.2% remainder after early-term, not a tok/J lever. FILE OWNERSHIP respected: specs.py (+41 additive lines, self-check PASS) + tb_adaptive_range.py (new) + this STATUS line only; integrator_conv.py/event_ctrl UNTOUCHED (tb_integrator_conv 5/5 + A7/A8/A11 + K=1 energy anchor preserved byte-identical); CASCADE/METRICS/RESULTS3/compiler/golden/digital UNTOUCHED. No git commit.

(analog attention-engine entry removed 2026-10-04: dropped from scope)

TASK #22 PARALLEL charge-summing super-tile (BUILT + VERIFIED in SPICE, PASS): the topology that makes cascade gain-error K-INDEPENDENT, unlocking deeper FFN K (#21's ~1.2x, now verified). NEW FILES ONLY: analog/testbenches/tb_supertile.py (falsifier), analog/schematics/top/chip_supertile.py (parallel assembly + charge-bus loss probe), + additive specs.py parallel-cascade law (parallel_cascade_snr_db / parallel_k_star / tokens_per_s_parallel + self-check). weight_tile/integrator_conv REUSED UNCHANGED; CASCADE/METRICS/RESULTS3, scripts/compiler/, digital/, scripts/golden/ UNTOUCHED. A7/A8/A11 anchors preserved (specs self-check K=1 = 4.12us/22.2 tok/s unmoved). No git commit.
  (1) CHARGE-BUS vs DIGITAL-SUM verdict (chip_supertile.charge_bus_probe, SPICE): summing K=4 partial charges (4x30 mV, ideal sum 120 mV) on a shared bus reads only 26.7 mV (attenuation 0.222 ~ 1/(K+C_bus/C_int)) — charge-bus summing is a K-WAY DIVIDER, LOSSY. => the super-tile MUST use the INT8 DIGITAL partial sum (exactly the paper's "partials leave as INT8 on the digital fabric", law:cascade). Charge-domain summing does NOT work in SPICE; digital-sum is the honest variant.
  (2) GAIN-K-INDEPENDENCE (THE claim, MEASURED on real SPICE partials): 4 window partials measured through the PROVEN single-column path (tb_tile_mvm._cal_1col_window, real pass_05 col0 weight_tile charge transfer + real event-rate/SAR converter): codes +19/+18/+23/+15. With the servo worst-seed gain error eg=0.44% injected (test_gain_servo model), PARALLEL super-tile output gain error is FLAT 0.440% at K=1/2/4 (= (1+eg)-1, K-INDEPENDENT) while the SERIES chain COMPOUNDS 0.440% -> 0.667% -> 1.125% (tracking (1+eg)^K). The parallel topology kills (1+eg)^K exactly as SERVO_EG.md/test_gain_servo assert #4 claimed. PASS.
  (3) AMORTIZATION + tok/s: parallel schedule == series (ONE conversion per K windows, partials INT8-summed) -> identical pass time / tok/s at the same K (tok/s x1.95 at K=4, verified == tokens_per_s_cascade); the win is DEEPER K, not a faster schedule. FFN depth (SNRs=38, SNRT=28): SERIES gain-capped at K=7, PARALLEL random-bound at K=9 (+2 K for free, gain term vanished). N4/7B heterogeneous tok/s/die (same pass(K)=max(136*t_q,T_conv/K)+4*t_q law, reproduces the landed anchors): SERIES 60,328 = 0.97x Sohu (FFN K=7) -> PARALLEL 74,844 = 1.20x Sohu (FFN K=9), a 1.24x lift — VERIFYING #21's ~1.2x projection.
  GO/NO-GO: GO as the tok/s lever, with the honest ceiling — the parallel super-tile delivers K-independent gain error (verified in SPICE) and lifts N4/7B from 0.97x to 1.20x Sohu, but NOT to 2x: once (1+eg)^K is gone the RANDOM sqrt(K) term at SNRs=38 caps FFN at K=9 (SERVO_EG.md). 1.20x needs the INT8 digital partial sum (charge-bus is lossy); past 1.20x to the K=14/1.95x point needs a HIGHER per-stage SNRs, not the parallel topology alone.


2026-09-07 — IMC research and faster iteration: read AGENTS/CONTRACT, Analog Compute notes and manuscript, checked primary literature and current Etched/Mythic disclosures. New review entry point: docs/src/content/Project/IMC_OPTIMIZATION_RESEARCH.md, with circuit/architecture/competitor reports and three experiment reports. Corrections: capacitor-coded weights are not consumed by read; current digital supertile performs K ADCs despite claiming /K amortization; paper 256/K*=64 means K*=4 (METRICS K*=64 is a transcription error); mini-N4 area model holds 11.95M weights/die, so 7B residency needs >=586 such dies; KV refresh tau/2 conflicts with its 4-bit budget and 524288*7.5fJ is 3.93nJ, not uJ. Old headline Sohu ratios/energy claims remain unsupported; no measured full-chip token benchmark was added.

New bounded experiments: (1) full-depth SmolLM2, two held-out note passages x256 tokens x2 seeds x2 noise levels x2 weight modes: protecting blk.11.ffn_down (0.833% of seven-projection MAC work) reduces simulated KL about5–8x; equal-work layer10 sham does not. This is teacher-forced noise modeling, not deployed W4A8 or generated-token quality. Naive INT4 baseline already roughly doubles PPL, so marginal recovery does not repair quantization. (2) SAGE-inspired permutation/range experiment:224 golden conditions PASS; layer0 FFN-down saliency interleaving improves44.28->51.13dB converter SQNR with D=1 and unchanged DATA ADC count, limited to3 new-mapping heldout tokens; checksum/fabric/physical error unmodeled. (3)19 Sky130 TG charge-average decks: calibrated averaging works after adequate settling; several fast corners fail; one fixed ADC incurs a larger recovered noise budget, so /K energy is not established. Reports preserve negative results.

Iteration improvements: depth research model uses batched attention matmul (median1.692->0.923s,1.83x) and exact-set top5 partial selection (0.270->0.035s,7.80x), retaining reference attention mode. All64 experiment cases rerun in130.4s; maximum KL difference7.96e-7/PPL-ratio difference2.09e-6 and identical argmax/top5. New --quick screening writes a distinct artifact and takes16.8s for a reduced workload. Shared SPICE runners use native wr_singlescale with dual-layout strict parsing and compact_output=False escape; solver/tolerances unchanged. Actual runner I/O tests,15 golden tests and tb_write_dac PASS; git diff --check clean. Cached Nix Python/NumPy and pinned ngspice43 used; no flow template or external note changed. Generated artifacts stay in build/research and build/sim. Work is uncommitted.

2026-09-09 — Continued circuit sizing, architecture and full-model convergence. Current entry point: docs/src/content/Project/IMC_CIRCUIT_CONVERGENCE.md. Research objectives are100/250 native useful TOPS/W at matched model quality and complete power (20/8fJ/MAC), not claims of achieved silicon. The provisional8-die/400W budget is a scenario, not a user production requirement. Architecture search covers810macros/12960scenarios with no old-topology point closing both residency and service. Inverse requested-rate budgets retain real attention/KV costs:70B/32Kcontext/500ktok/s would require21.475PMAC/s attention and1.342PB/s packed4-bit KV traffic; the weight engine alone needs695W at100TOPS/W or278W at250. Compute-bound operation remains a capacity/bandwidth/service requirement.

New passive signed16x8/128x8 Sky130 fixtures remove the standing compute OTA and retain bit significance in charge, h_next=(h_previous+partial)/2. At16rows, reducing matched reset widths6.72->0.84um saves2.47x interface energy (14.7045->5.94655fJ/MAC, same5planes/265ns). At128rows those small resets fail;3.36um restores fixed8-plane69.66dB/5.14027fJ/MAC at424ns. Dynamic7/6/5planes reaches4.499905fJ/MAC/318ns nominal but failsSS85. Saved-waveform diagnosis identifies incomplete sharing. Extending only share hold7.6->15.6ns repairs it: TT27=4.499809fJ/MAC,0.042771MAC RMS/0.079342max; SS85=4.587238fJ/MAC,0.103329RMS/0.223379max;366ns average. Both pass original numerical gates. All are noiseless W4A8 interface simulations, zero ADC services, fixed coefficient caps, ideal sources, no SRAM/reference generators/clock tree/extracted junction or wiring. Small compiler-derived fixture mean|W|=.6631 does not represent actual W8 slice loading.

Capacitor/mapping studies preserve unfavorable results:1440 calibration cases and48 full-model cases show exact characterization can reduce mismatch while noisy redundant coding can worsen error and increase switched C. W8/Cu4fF assumed mismatch adds at most0.114% observed PPL versus its own W8 reference, without temporal ADC errors. Full radix replay covers26 cases with exact partial conversions and explicit ADC clipping/noise; unsmoothed100uV read noise plus independent sharing fails quality. Frozen channel scales improve it. A calibration-only alpha grid across210MVMs reduces mean local NMSE17.1% and passes4/4 reused noisy validations, but frozen choices fail fresh-note acceptance (3/4 noisy and1/2 ideal-A8 controls pass); no holdout retuning. Actual W8 low-slice medianC is about3.6pF, far above the old circuit fixture. Reports: IMC_CAPACITOR_SIZING.md, IMC_RADIX_FULL_MODEL.md, IMC_SMOOTH_RADIX.md, IMC_OUTLIER_PLANES.md. Their different error families have not been combined into a verified chip model.

Responded specifically to Mythic's nulled columns using usernote27h10 and primary patentsUS10389375B1/US10255205B1. Local correction with shared precision reference is transferable; old NULLSEEK rejection was topology-specific and mistook a comparator test bar for a noise floor. Added scope corrections without rewriting historical documents. SAR early residues can be fullscale; common-mode servo gm is not automatically differential restoring conductance; passive packet connection is charge sharing, not ideal additive injection. New IMC_MYTHIC_NULLING.md records these distinctions. Complete split6+4 CDAC prototype now has actual comparator-driven10-bit feedback. Initial weak reset caused33LSB error and free initial DC acquisition understated steady-cycle energy. A3.36um reset and fixed-1.9mV reference trim pass12 separate test inputs atTT27/SS85 within1LSB, with paid reset and acquisition. Further energy/timing sizing and8-column validation are recorded in the dedicated null-SAR report as completed; no transient-noise or matrix-integration result is implied.

Fixed grouped-weight experiment: group128 symmetricW4 second-order compensation versus matchedRTN,512-token27h3 calibration, originalQ8_0 full-model reference on two separate256-token notes. All20cases fail jointKL<=.01/PPLratio<=1.01, despite89.5% lower mean local calibration NMSE. SymmetricW5 (sign+4magnitude bits, one bank) also fails all8 weight-only/ideal-A8 screens. Neither can replace W8 at equal quality. Explicit single-bank counts, -16 rejection for symmetricW5, partial/group scaling and blocked compensation were independently checked. Artifacts and frozen codes remain inbuild/research; source/report: imc_grouped_w4.py and IMC_GROUPED_WEIGHTS.md. W4run122.00s; W5screen48.49s, one BLAS thread.

Additional iteration check: cached ngspice43 KLU versus Sparse on identical16x8 replay gives18.0958->17.4601s (1.036x single run, not meaningful speedup), maximum recovered difference2.726e-6MAC and energy difference.001293%. No global solver default changed and no KLU noise support assumed. Prior compact output/batched model improvements retained. Flow templates, external notes, production circuit contract and operational scripts/compiler/golden numerics unchanged. All work remains uncommitted; generated outputs are underbuild/.


2026-09-09 — Null-SAR continuation: the energy-sized full-acquisition/reference-graded candidate passed the twelve-input development set but failed the independent eight-column SS85 history by up to 6 LSB. Those inputs are now exposed development cases. Widening just the two non-MSB coarse reference branches from 0.84/0.42 to 1.26/0.735 µm follows the floating-top switched load Ci(1−Ci/Ctotal). With the same −1.9-mV trim and 295-ns cycle, exact replays of both failed column histories now return all six target codes. Both twelve-input corner regressions and the eight-column TT regression also pass; the remaining SS/control/fresh-seed suite is still pending at this entry. The twelve-input set contains eleven levels absent from the three-input calibration and one repeated level with different history. No broad noise/yield or full-macro claim is implied.

The existing two 8-kΩ/60-fF input filters were checked with an independent 8,192-trajectory stochastic RC model and split-capacitor charge equations. Stationary comparator-node resistor noise is 364.87 µV differential RMS at 27°C. The passive settled signal gain is 0.927536, giving 393.37 µV referred to the ideal held residue. Enlarging both filters attenuates signal as well as noise; the instantaneous restricted model minimizes at Cf/Ch=sqrt(2), giving 177.34 µV for Ch=768 fF. This is not a bound on a clocked ADC with finite sensing time. Hypothetical boxcar intervals for 100 µV are 11.852 ns at the comparator nodes or 13.857 ns referred through settled gain; neither is a measured StrongARM aperture. Source: tb_imc_filter_noise.py; report: IMC_TRANSIENT_NOISE_PATH.md. All analytic/stochastic checks pass in under one second; MOS/reset/reference noise and real sensitivity remain uncharacterized.

The fixed grouped-weight format screen extended through symmetric W6 and W7. W6 all eight controls fail; W7 two of four weight-only controls pass but none of four ideal-A8 controls pass. Runtime was 46.2/46.5 s with one BLAS thread. Proposed single-bank W6/W7 require five/six magnitude bits, with GPTQ median modeled column loads 4.312/8.640 pF, not the earlier W4 circuit load. No ADC/noise sweeps or equal-quality energy reductions were assigned. Independent arithmetic/capacitance/count/clipping checks pass, including rejected −32/−64 endpoints and unchanged default W8 behavior through −128. Artifacts imc_grouped_w6_screen.json and imc_grouped_w7_screen.json preserve all controls; IMC_GROUPED_WEIGHTS.md labels reused passages as development screens.

Closed eight-column TT solver experiments preserve exact codes and receiver/trial histories: Sparse50 179.98 s, KLU50 269.65 s, Sparse100 226.72 s. Maximum signed-energy difference was 0.003916%; no demonstrated wall improvement, with substantial setup timing variation. HSA early model pruning was then rejected as an identical-model optimization: compiled native/HSA checks changed seven of twelve model bins at width boundaries despite identical W/L/nf/m/junction geometry. The default settings remain native. Reproduction and source/compiled evidence: IMC_ITERATION_SPEED.md and IMC_NULL_SAR_REVIEW.md; the expected-failing --hsa-bin-audit exits 1. An isolated native-semantics pruning build is being investigated separately; no speed gain or simulator replacement is claimed at this entry.

2026-09-09 — Further null-SAR, architecture and simulation continuation. The RC-sized two-level converter completed its twelve-input/eight-column TT/SS development suite, but frozen seed9952 subsequently failed SS by2LSB (809.306→807). Independent trace audit verified all240 actual trial states and the2059.684/2060.835fJ development/fresh SS energy integrations; the failure is physical/numerical transfer behavior, not decoding or normalization. It remains rejected as broad convergence.

A physical three-level VCM-start SAR now performs ten actual comparator decisions and nine half-span bottom updates, with real CMOS selectors and per-column isolated references. Original frozen trim−1.9mV,295ns: three calibration inputs pass TT/SS at1432.40/1459.77fJ; twelve development inputs pass at1454.52/1483.40fJ, about42% below the original345ns reference on identical inputs. The exposed SS9952/column7 history now passes within1LSB (codes898/64/810). Full three-frame/eight-column TT then timed out at the unchanged600s guard, producing no accuracy verdict and stopping subsequent cases. A shorter eight-column one-measured-frame control completed in566s with max1/RMS.500LSB and1306.06fJ/service on that different input set. It required502937iterations for30555accepted rows; source/model setup was only6.37s. Initial acquisition dominates nonlinear iteration work. Stiffening only the unused HI/LO rails retains CM sampling isolation and passes calibration at1395.59/1417.32fJ, but paired2ns controls do not repair startup timestep churn. Its further validation is pending. All earlier circuits, runtime failures and raw decks are retained inbuild/sim; IMC_NULL_SAR.md records the distinct boundaries.

Native-bin pruning is now qualified as an opt-in iteration improvement for the audited nominal Sky130 wrappers.35 tiny gates pass, including TT/SS exact compiled geometry/model/readable-coefficient identity, conservative fallback and original failure behavior. The same-binary frozen TT8 control fell216.57→145.15s (observed1.492×), with identical complete traces, eight codes,80physical decisions, both energy metrics,21398rows and68801iterations. The archived4LSB wrong-bridge failure is preserved. Reported program size fell1461.1→346.1MB; this is not measured peak RSS. HSA remains rejected because it changes native model selection. Patch, tests, local wrapper and scope: IMC_ITERATION_SPEED.md. No installed simulator/PDK/flow default changed. This timing result does not guarantee speed on the new VCM topology.

The VCM timeout exposed lost simulator diagnostics: both shared runners now stream stdout/stderr into their per-run log, preserving emitted output on timeout while keeping existing timeouts/commands/solver settings. Actual compact/legacy RC traces remain identical, and real failing/timed-out child controls preserve both streams and exception types. test_spice_io.py passes. This does not force ngspice's own stdout buffer to flush and does not alone accelerate nonlinear solving.

Fixed W8/A9 replay retains the original frozen scales/codes: both ideal-input controls pass, but ten-bit ADC-only passes1/2 and noisy cases2/4 at100µV or3/4 at50µV. ADC count is unchanged; activation magnitude-plane work increases7→8 (+14.29%). The preselected R256/A9/ADC11/read50 follow-up then passes both ideal and both ADC-only controls, but still only3/4 noisy cases (worst PPLratio1.017448). Actual512-token services fall920125440→530841600 (42.3077%, independently tallied from checkpoint dimensions); A9 separate-plane counts7361003520→4246732800. Modeled low/high medianC grows3.580/.524→6.980/.828pF. Runtime211.39s, one BLAS thread; no physical R256/11-bit/50µV energy or timing is assigned. Source/report: imc_smooth_radix.py and IMC_SMOOTH_RADIX.md; all unsuccessful controls remain saved. Subsequent A9 runs enforce the original A8 artifact's frozen-scale hash and record ordered weight-code hashes; no holdout retuning.

A fast exact split-capacitor reference-load screen enumerates1023prefix states and checks full-node charge/energy identities. With the stated settled60fF filter, midpoint load grows55.65→205.91fF per column; the equal-three-rail slowest-mode capacitance is460.54fF. Under the illustrative250mV→100µV/12ns mode-decay allocation, eight coherent columns require midpointRout≈931ohm if other sources are ideal. A passive equal divider across.5V then costs2.475pJ net or5.693pJ positive ground-referenced port delivery per295nsservice. These are topology/allocation screens, not universal energy/noise bounds. They motivate a low-quiescent bidirectional shared buffer with explicit reset/threshold distribution. Source tb_imc_reference_load.py; IMC_NULL_READOUT_OPTIONS.md includes limitations and the finite-reference follow-up.

Exact pinned OpenVAF/VACASK isolated builds and runtime dependencies now succeed. Upstream RC transient-noise regression passes1.77s/240004points: maximum PSD disagreement1.287dB; independent analytic PSD relative error9.42e-7 and variance1.00656×kT/C; zero-noise control is exactlyzero. Native BSIM4.5 versus explicit4.8.2 matches current/intrinsic capacitance to floating precision at TT27/SS85 for the two actual comparator geometries (438biases/device), but stationary thermal-noise PSD differs by up to1.186×NFET/2.430×PFET atTT. DC agreement is not noise equivalence. A new listing-r extractor retains all347NFET/344PFET explicit coefficients without truncated getters/listings; flat native4.8 replay exactly reproduces all14 tested DC/charge/capacitance fields at both corners. Sources tb_imc_bsim_revision.py/tb_imc_flat_model.py and IMC_TRANSIENT_NOISE_PATH.md. VACASK model-port/noise qualification and clocked-latch sensitivity remain active work. No full-chip tok/s, tok/J, measured competitor victory or global optimum is claimed; production numerical contracts remain unchanged.


2026-09-09 continuation — VCM series-resistance diagnosis, physical startup and model-noise qualification (research only).

The original VCM-start full TT8 seed9951 run passes after a physical first-warmup comparator pulse, at1.35054pJ/service; SS8 fails max5LSB at1.37714pJ. The pulse preserves all80 decisions in its matched bounded8-column control, with maximum residue change0.0355µV and steady-cycle energy change0.0371%; observed wall568.1→94.5s, iterations502937→78373. Warmup delivery rises1.12895→1.23578pJ/column and is separately paid. This is a physical initialization change, not bitwise simulator equivalence or free cold start. A stiff-end-reference simplification passed three calibration points but underflowed at1.053µs in TT12; that failed branch remains archived.

A768fF floating negative holder with its real resetTG and unchanged8k/60fF filter passes three-point calibration at−0.7mV trim, but still fails the exact SS9951 column5 history:588/747/768 against587/746/763. Deferring valid until comparator reset also fails. Waveforms locate a concrete series-TG settling problem: the largest DAC bottom is8.454mV below HI at the trial768 aperture. Doubling only RC-derived reference-switch widths (before minimum-width flooring), retaining1.68µm acquisition and the original timing, repairs allthree codes. Same-case positive delivery rises1.382817→1.431707pJ/service (+3.53549%); signed net slightly falls and is reported separately. Largest bottom error drops to0.425mV; weighted bottom error at that trial drops2.292812→0.113730mV. Independent fullnodal reconstruction agrees for all30 decisions; rail droop is already included and must not be added twice. The fixed candidate passes TT/SS12 at1.45114/1.51471pJ, max1LSB, and TT8 at1.41724pJ. Broader SS/fresh validation remains active at this checkpoint; seed9953 is untouched. Nonunit reference scaling now requires both RC grading and wide acquisition so the option cannot silently grow acquisition devices. See IMC_NULL_SAR.md and IMC_NULL_SAR_REVIEW.md.

The new passive reset-noise screen tb_imc_holder_noise.py explicitly includes conserved random charge after equilibrium reset. Added negative768fF/60fF alone contributes76.27/83.32µV referred persistent noise atTT/SS; an independent identical two-holder hypothesis gives107.86/117.83µV before MOS/reference effects. A16ns ideal boxcar leaves99.23/108.39µV for the negative branch including resistor noise. The real positive split-CDAC is not replaced by that symmetric hypothesis. EquilibriumLyapunov and16,384trajectory branch-current checks pass in~0.5s; boxcar variance error0.734%, conserved-mode variance error1.162%, charge drift1.04e−30C. Euler discretization is explicitly a~0.79% fast-mode stationary bias; the5% stochastic gate is a sanity screen. Larger capacitance or paid correlated sampling need actual clocked validation; waiting cannot average away a conserved reset mode. See IMC_NULL_READOUT_OPTIONS.md.

The VACASK BSIM4.8 implementation required four missing derivative terms repaired in an isolatedVA/OSDI variant. CorrectedVA/native4.8 spectra pass TT/SS, including21 fixed forward/body/reverse bias points. Matched native DC export requires top-level noise-job D/S topology; its repeated jobs skip DC plot numbers, so assuming dc1,dc2,dc3 exported integrated-noise scalars. tb_imc_flat_model.py now selects the preceding DC plot and asserts73point sweep/drain identity, log errors and data hashes. All14 correctedVA/native4.8 DC/charge fields then agree within1e−14 of their field peaks. Original failures are preserved.

Native4.5 and4.8 thermal-noise equations differ substantially under the expanded biases. A separate explicitly named4.8 electrical model with legacy4.5tnoi1 equations passes stationarynative4.5 spectra within1.31ppm atTT/SS across21biases. This is a hybrid research model, not full4.5 equivalence. AllfiveactualStrongARM geometries are now exported and exactly replayed against native4.5: Ninput3.5µm/bin26, Ntail.42/bin170, Nregen1/bin71, Pregen2.25/bin35, Preset1/bin80, allL.15,nf1. Source tb_imc_latch_model_export.py,438zero-body bias points/geometry/corner. Native4.8 fails the all14field revision comparison on cgs/cgb/cds/cdb; the earlier Id/Cgg agreement must not be described as blanket capacitance compatibility. Sourceaudit identifies a body-derivative term changed from(1−T5) to(T4−T5) in capmod2. An independent24center body-charge finite-difference audit confirms identical qg/qd curves and matching4.8 derivatives (≤3.98e−9of fieldpeak), while4.5 derivatives differ up to2.46%of peak. Deterministic clocked comparison is underway before any latch-noise result; see IMC_TRANSIENT_NOISE_PATH.md.

The frozen model sweep now records ordered weight-code hashes separately peralpha profile; its existing numerical results and accepted production paths are unchanged. Targeted syntax/selfchecks and git diff--check pass; simulatorI/O retention checks pass. No fullmacro noise/yield/PEX, matched tok/s/tok/J superiority or global optimum is claimed.


2026-09-09 — Executable system benchmark requested for the Mythic comparison. Added scripts/compiler/metrics/imc_system_benchmark.py and docs/src/content/Project/IMC_SYSTEM_BENCHMARK.md. One cached-artifact run reports native weight TOPS, power, TOPS/W, fJ/MAC, conditional tok/s and tok/J at the same work/time/energy boundary. Default is explicitly one128×8 logicalW8A8 macro with two serial coefficient banks, eightADCs,8B-class shapes,batch1,context2048; W8 loading/storage and complete model activity remain projections. Exact shape counters include the full LMhead and separate untied embedding storage; attention/KV/fabric/programming counts and missing costs are explicit. PVT/source hashes, fixed twelve-input ADC stimulus, full-cycle positive-delivery sums, complete development signatures and allfour9952/9953 regression files constrain evidence selection. Missing or failed gates never populate validated_chip_metrics.

Independent benchmark review repaired three accounting risks before delivery: weight groups are reused across the batch without free coefficient copies; serialized memory-service times are summed in the memory-margin gate; power-throttling waits are explicit and charge static energy. Dimensional, W4/W8, padded-work, sharedADC, batching, slow-memory, insufficient-residency and power-limit selfchecks pass. --require-validated returns1 as expected because integrated macro/noise/layout/token execution and19 scenario inputs remain unqualified. Results and editable inputs are in build/research/imc_system_benchmark/. Legacy scripts/compiler/metrics/report.py also lost an erroneous extra1e-3 factor that understated TOPS/W by1000×; its older workload/model assumptions are otherwise unchanged.

Concurrent circuit progress: frozen paired-interior calibration selected−1900µV with no negative holder and reference-switch scale2. Full five-case development suite passes at1.51467/1.55808pJ for TT/SS12 and1.42037/1.45625pJ forTT/SS8;345→295ns service gain remains16.9%. Both9952 TT/SS pass, including the previous low-code failure; first untouched9953TT passes at1.44086pJ.9953SS is still active at this checkpoint. No fullchip or matched competitor victory is claimed.

System benchmark evidence-adapter verification completed: all8 permanent cached-artifact tests pass (~1.8s). They reject duplicate/mislabelled corner and bridge controls, altered frozen inputs, PVT mismatch, missing reset/closing cycles, signed-net/invalid energy substituted for positive delivery, changed candidate configuration and incomplete/failed regression coverage. Mutations stay in memory. Benchmark selfchecks, strict unvalidated exit1, syntax and whitespace checks pass; default outputs refresh in well under1s without SPICE.


2026-09-09 — User requested a one-to-one Mythic hardware comparison. Primary-source checks identify historical M1076 as76 compute tiles plus7 control/I/O tiles,79.69M logical8-bit weights and19,456ADCs. The official ISSCC preliminary press kit separates8-bit16.6TOPS/3.3full-systemTOPS/W from5.2arrayTOPS/W; this is retained separately from the25TOPS/3–4W product headline. CurrentM1 implementation identity is not inferred.

The system benchmark now emits mythic_comparison.md/json matching both79,691,776logical weight positions and19,456ADC instances. Equal weights alone would grant77,824small128×8 W8 macros622,592ADCs (32×Mythic); equalADCs alone provides1/32of its weight capacity. Joint mapping groups1,024small macros behind256ADCs, requiring32rounds perW4slice and2serial slices:19.612µs,8.12684conditionalTOPS. Full-range8-plane timing alone gives8.027TOPS, with no new energy/accuracy assignment. This remains a proposed architecture;9.145µs charge holding, mux/kickback,15,360reconstruction additions/group, storage, distribution, area and fullchip power are unvalidated. Failed reservedADC regression staysFAIL. Matched token metrics remainnull; no measuredMythic victory. Counts, timing, energy identities and all8 evidence-adapter tests pass.

2026-09-09 — Analog latch/flip-flop hypothesis checked against primary Mythic patents. US10255205B1 discloses local multilevel charge state for both input DACs and ADC cancellation-reference DACs; US10389375B1 separately discloses multiplexed column-current readout and binary decision/output states. Neither establishes a shipped lossless analog-result latch. Stable current-array inputs may permit direct selected-column readout; this is explicitly a mechanism inference. AnalogIOC already retains accumulation on capacitors, but the9.145µs shared-ADC wait needs retention/read-disturb qualification. Added timing-only controls: ideal removal of array/hold overhead still caps the fixed19,456ADC/295ns/currentservice-count mapping at8.44193TOPS; preparing and immediately converting small groups avoids long queuing but gives3.76758TOPS without overlap. No energy/retention credit is assigned to those schedule controls. A bounded actual-switch hold experiment is underway separately.

2026-09-09 — Completed the bounded analog-storage experiment in tb_imc_hold_retention.py; results and limitations are in IMC_HOLD_RETENTION.md. Three frozen levels at TT27/SS85 use the actual minimum programmed accumulator capacitance, 304 fF, and existing isolation/reset TG sizes. Over the 9.145 µs ADC queue, native-geometry maximum drift is 30.91 µV and assumed nonzero-diffusion maximum is 72.57 µV. Lowering numerical gmin changes SS drift to at most 44.22 µV, so these are model-sensitive deterministic results, not precise silicon leakage predictions. The injected 100 pA discharge fails as intended and integrated capacitor current agrees with C×ΔV. Sampling/isolation/input-return error is separately 1.68–11.43 mV; no 100 µV absolute accuracy is claimed. Missing gate/capacitor leakage, noise, mux/read disturb, mismatch and extraction remain explicit. Five tiny runs complete in 21.12 s. System comparison links the completed experiment without assigning integrated retention or throughput credit.

2026-09-09 — Prepared IMC_ANALOG_STORAGE_HANDOFF.md at the user's request for a new integration session. It records the standalone-only storage status, reproducible candidate configurations/artifacts, failed reserved SS ADC case, equal-resource conversion ceiling, connected charge/loading and decode constraints, staged physical integration, and matched token-performance acceptance. Source review confirms that the current signed array has one stored output per column, not an existing differential pair; a differential alternative must add and account for that hardware. No new circuit simulations or token speedup are claimed by this documentation change.


### 2026-09-10 — autonomous IMC discovery and falsification round

Added `docs/src/content/Project/IMC_DISCOVERY.md` and independent circuit, critic and
prior-art reports. Searched supplied circuit notes plus fresh primary papers,
patents, official Mythic disclosures and Sky130 process documentation. Broad
analog pooling, capacitor reuse, radix and exponent-alignment novelty claims
have close prior art; no new first-invention or Mythic-victory claim is made.

New `scripts/compiler/metrics/imc_native_charge_analysis.py` verifies the original-cap
charge invariant, incorrect equal-voltage-copy and unaligned-scale controls,
power-of-two zero-upper-plane alignment, 200,000-draw linear noise covariance,
optimized ADC decision-energy bounds, seven saved tensor sums and conditional
service schedules. These mathematical/model checks pass; chip metrics remain
unknown. Early pooling before radix accumulation improves median modeled
mismatch error 0.966→0.248 MAC versus eight independently calibrated partials
at assumed 0.1% independent ratio sigma; no foundry/ADC/noise claim follows.

New `analog/testbenches/tb_imc_native_charge_pool.py` ran ten deterministic
Sky130 fixtures: eight groups of four fixed W4 coefficients, real row/reset/
sharing/pooling TGs, ideal capacitors/references/clocks and a 948-fF load, NO
ADC or programmable memory. Five bounded ternary cases pass; five cases fail
(one fast SS ternary and all four A8 variants). SS ternary sharing40→100ns
repairs RMS0.388→0.0172 MAC on development inputs. Fresh seed97103 at frozen
100ns passes TT/SS with RMS0.00633/0.02057 MAC; SS50ps numerical control
passes and changes recovered output by at most0.000261 MAC. The final bus is
independently calibrated per configuration/corner. A8 original/dummy-balanced/
reset-reuse/early-pooling RMS is6.251/5.974/4.704/3.704 MAC: all fail the
unchanged<0.25RMS/<1max gate, with artifacts preserved and nonzero exits.

Independent review caught source hashing after simulation; new runs freeze
source bytes at import and save a generator snapshot. All ten generated deck
fingerprints were independently checked; `build/research/imc_discovery_manifest.json`
records exact on-disk deck hashes and which source snapshots exist. Earlier
source hashes alone are not authoritative. Research noise budgets remain
many integer MAC units at illustrative B8 capacitances, and4fF ideal units
still lack legal extracted capacitor realization. Existing system benchmark,
production circuits, local notes and flows were not changed.


2026-09-10 — Analog log/charge/exp and pipeline round, followed by the authorized ten-hour whole-repository research campaign. New entry point docs/src/content/Project/IMC_GMID_PRODUCT_SIZING.md. Real Sky130 scalar multiplication uses gm/ID tables plus independent actual-bias diode/exp DC/AC characterization. The selected table23/L0.5 coordinate yields W1.86um, operand reference256.893nA, physical reference ratio1.5 and600fF state. Frozen1.2us acquisition/100ns evaluation/200ns closing gives1.5us complete words: fresh short-cohort TT max0.87742%, SS0.64736%, about2.768pJ/product; TT half-timestep changes relative product by at most2.676e-6. These deterministic positive centered-mantissa gates pass; noise, mismatch/yield, signed accumulation, input conversion, actual receiver and density remain unverified. Fast1nA, initial sizing populations, output-width shortcut and shortened-corner failures are preserved. A102-word grid aborts numerically; equivalent sensing-source removal, redundant-PWL removal and timestep controls shift or preserve aborts without completing it. No extrapolated grid accuracy is reported.

Fresh exact current128x8 normal-number core TT/SS runs reproduce previous selected3-word results: RMS0.04277065/0.10332862MAC,4.499809/4.587238fJ/MAC ideal-interface energy,366ns mean. Both decks byte-identical to saved baseline; sources and original artifacts unchanged. Source/deck/trace/executable snapshots are in build/research/imc_current_core_baseline. The physical two-bank holder experiment supports scheduled395->295ns issue interval but fails capture/read accuracy; no pipeline throughput credit. Separate research reports preserve primary prior art, charge/log equations, gm/ID slopes, conditional noise/area limits, source/energy audits and failures.

At2026-09-10 22:37:37UTC the user authorized a ten-hour autonomous campaign using the entire repo and new literature toward demonstrated SoTA analogIMC. Active goal and docs/src/content/Project/campaign/README.md record deadline2026-09-11 08:37:37UTC. Parallel circuit-archive, model/system-archive and freshSoTA evidence maps underway; logscalar is one candidate, not a restriction. Continue research across compactions and checkpoints.

### 2026-09-11 00:20 UTC — autonomous campaign checkpoint

Whole-repository evidence maps and current primary-literature comparisons are
in `docs/src/content/Project/campaign/`. The active ten-hour campaign continues until its
08:37 UTC target. `POPULATION.md` preserves competing mechanisms and failures.
Dense W8 sizing now uses frozen 256-row common-A10 fixtures, actual-biased
switch gm/ID/conductance, explicit diffusion controls and complete-transient
checks (`DENSE_CORE.md`). A 200-ps reset slew crosses a previously failing
numerical boundary; full dense product validation is still running.

The first conditional intrinsic StrongARM noise experiment estimates ~445 µV,
not the assumed50 µV; numerical/statistical controls are running and no final
ADC noise claim is made (`DECISION_NOISE.md`). Fixed-charge pooling has a
constructive model result when clipping alone is removed; finite range,
noise, differential useful-half mapping and physical capacitor-stack readout
remain under independent circuit/system criticism. No SoTA or novelty victory
has been established.

## 2026-09-11 01:32 UTC — autonomous campaign extended

User requested another 48 hours of parallel analog IMC research. New target: 2026-09-13 01:32:38 UTC, superseding the initial ten-hour deadline. Current dense-core, gm/ID comparator noise, finite-range system, physical pipeline and guard-stack experiments continue under their frozen gates. See [campaign record](campaign/README.md). No integrated SoTA claim has been established.

## 2026-09-11 12:40 UTC — recovered research and new pipeline result

Interrupted jobs were audited against saved completion evidence; missing handles
and incomplete traces were preserved, with distinct retry directories. The
calibration-predicted +7.5fF native ping-pong trim now passes full nine-word
TT deterministic validation:0.061411/0.086652MAC RMS/max; retained validation
0.067588/0.086630MAC. No physical ADC, sampled-noise/PVT yield or throughput
claim follows. See campaign/NATIVE_PIPELINE.md.

The reset/share noise identity gives stationary kT/C rather than the prior
sharing-only2kT/(3C). Frozen matched system controls and physical two-cap
stochastic controls are running. Programmable-bank AC loading reveals a
9.66fF zero-code floor for the tested unsigned4bit/Cu4 bank; active capacitor
counts are not installed area. Connected guard-stack settling repairs do not
remove its remaining held-out error; failures remain documented.

Root resumed incomplete256-seed comparator cohorts by revalidating retained
decks and waveforms and simulating only missing seed indices under new names.
Substrate2 MIM coupons are being built for physical area/parasitic checks.
Completed waveform archives were losslessly compressed with per-file SHA256
verification, freeing10.979GB. No integrated SoTA or novelty claim is made.


### 2026-09-11 13:10 UTC — native pipeline and thermal-model audit

Frozen +7.5 fF native-holder trim passes deterministic capture/retention at TT and SS85 with independent corner affine calibration; frozen-TT affine coefficients fail at SS85. A physically selected 7.5 fF capacitor (3 MOS/bank) also passes both tested corners. An always-OFF replica share TG to VCM passes TT (0.011084 MAC RMS) and SS85 (0.117203 MAC RMS), with no added trim MIM; fresh ±14224 MAC history stress and matched serial controls remain in progress. No ADC, full-core noise, mismatch yield or SoTA claim. Reports: `campaign/NATIVE_PIPELINE.md`.

Native Sky1304.5 TNOIMOD=1 stationary on-TG noise is approximately0.83×4kT Re(Y), explaining the observed approximately0.82 kT/C switched-noise result. Independent resistor Nyquist oracle passes and hybrid/native spectra closely agree. TNOIMOD=0 overshoots to approximately1.14; no automatic model substitution was made. Continue physical kT/C budget, do not claim the model deficit as a capacitor-size improvement. Actual DC VDS is below2e-14 V in the audited fixture. Report: `campaign/RESET_SHARE_NOISE.md`.

### 2026-09-11 13:15 UTC — system continuation: reset, programming, storage and fixed mismatch

Recovered completed balanced16 grids and preserved incomplete radix9 grids. Corrected ideal reset/share kT/C campaign completed Cu4 35/36 and Cu8 36/36 with source hashes verified; radix9 rows all pass their six development cases. Measured unsigned programming C(code) sensitivity completed18/36 with no complete architecture survivor; radix9 separate misses one case near KL.0102/.0103. New `RESET_NOISE_PRECISION.md`, `STORAGE_SHARING.md`, and `FIXED_CAP_MISMATCH.md` preserve scopes, negatives, capacity/area envelopes, primary SRAM/PICO/8T1C references, fixed-per-cap coefficient checks and redundant-carry oracle tradeoffs. Fresh programmable digit calibration completed; signed8/balanced9 fixed mismatch and frozen old-corpus offset-calibration full-depth grids are active. No silicon yield, full programmed-core validation, full-model resident capacity or SoTA claim.

### Autonomous IMC campaign — 2026-09-11 13:35 UTC checkpoint

User requested a comparison with initial session results before continuing.
Saved `campaign/SESSION_COMPARISON.md` and continued physical/system experiments.
Fresh 256-seed comparator cohorts do not confirm the earlier capacitance noise
benefit; paired difference intervals include zero, while energy/delay increase.
Pipeline extreme arithmetic fails in both replica and matched serial, though
retention and moderate random-history tests pass. Matched small-width original
dense digits fail both physical/raw gates; balanced digits pass the provisional
physical screen at the same sizing. Eight MIM coupons pass full DRC and native
terminal-matrix checks. Contact-only top metal reduces extracted top loading
but leaves bottom parasitics. New physical FIA resolves eight deterministic
signs and exposes acquisition/loading/reset errors; gm/ID and individual port
currents are measured before optimization. System fixed-mismatch corrections
remain under test. No complete Mythic/SoTA improvement is demonstrated.

Lossless readback-verified compression of the newly completed comparator traces
is running; raw removal occurs only after per-file hashes verify.

### 2026-09-11 13:41 UTC — System mismatch controls completed

Both rank1-corrected36-case fixed-capacitor-mismatch grids and both12-case paired0/10/20µV read-noise grids completed with source hashes intact. No rank1 candidate passes all six cases on either modeled die. Signed8 A11 separate still fails one die with ideal readout while retaining stationary kT/C, so comparator noise alone cannot be presumed to rescue quality. All eight20µV paired cases exactly reproduce parent results. See campaign/LOW_RANK_CORRECTION.md. No system-quality, yield or SoTA claim follows. All system campaign jobs from this round are finished; compact evidence is retained.

- 2026-09-11 native-pipeline bounded phase/sizing round: late share settling is
  quantitatively negligible (<0.023 µV motion), while opposing switch-on/release
  nonlinearities dominate fullrange transfer. Frozen complementary half-width
  dummies FAILED (serial/replica max28.364/26.275MAC), principally because ON
  dummy capacitance worsened array input-charge linearity. Fixed-total-width
  4.48N/8.96P native controls also FAILED strict gates: serial max improves
  9.756→6.738MAC, replica max7.974→7.424 but RMS worsens4.159→5.088MAC.
  Native retention still passes; no nominal accuracy solution or SoTA claim.
  Actual bias trajectory gm/ID, gds and terminal charges and all failed traces
  preserved. See campaign/NATIVE_PIPELINE.md; no jobs remain from this round.

### Autonomous IMC campaign — 2026-09-11 14:25 UTC checkpoint

Completed actual-bias programmable-bank sizing and SS repairs. W=.42/8ns
fails, .42/16ns and .84/8ns pass independent timestep checks; .70/8ns also
passes, smaller-width boundary controls continue. Actual4/6/8fF-class
Substrate2 MIM coupons pass full DRC and terminal-matrix checks; bottom
parasitics are about6.9/5.7/5.0%, not the large coupon's1%.

Physical N4+FIA achieves gain47.29 but fails fine/native gain ratio (~.926).
Extra20ns reset fixes native reset residual; quiet-bus clamp adds energy
without fixing gain ratio. Independent native-port LTV improves FIA signal
model agreement to.37%/1.39% for L.18/.30; noise remains conditional and
reset/acquisition covariance must be propagated rather than double-counted.

Broader Cu8 noise seeds overturn initial two-seed robustness. Compiler
decomposition identifies discarded originalQ8_0 group32 scales as the
dominant clean error floor. GPTQ did not improve the tested frozen corpus;
original-group-preserving architecture and paid partial-read costs are the
next system branch. No complete SoTA/Mythic result is established.

Verified lossless archival of12 completed bank traces freed another2.021GB;
source/decks/results/AC matrices and all negative outcomes are preserved.

### 2026-09-11 14:37 UTC — continuation and fresh-stimulus control

Prior round classified as progress: W0.50 SS85/8ns bank passes independent
1/0.5ps numerical control. W0.48 finer run remains live. Added explicit
manifest-recorded row amplitudes to the programmable bank TB, retaining
legacy defaults and fixed full-scale gates; the timestep auditor now
rejects mismatched stimuli. Running fresh eight-amplitude W0.50 SS85
control, not reusing the five sizing amplitudes. Prior-art checkpoint
FIA_PIPELINED_PRIOR_ART.md confirms generic FIA pipelined SAR is known.
The independent 1pF FIA input control passes signs but reveals substantial
input loading; output-isolation and raw32 system calibration remain active.

### 2026-09-11 14:44 UTC — system precision checkpoint

The eight-seed Cu8 check falsified the earlier two-seed robust-quality inference: first-passage physical cases pass only3/8 and4/8 on the two fixed dies, although all KL cases pass. Paid +1ADCbit/span÷2 also fails to robustly rescue it. Exact-readout decomposition identifies old whole-column W8 recompilation as the dominant clean floor. Ordinary frozen GPTQ improves calibration MSE210/210 but worsens exposed quality. Original group32 Q8_0 scales retain much stronger ideal margin; calibrated Cu4/40µV single-holder-reference physical quality is now running. The completed group64/128 ideal diagnostics also pass with PPL ratios≤1.001797/1.003668 and require3.2×/1.733×, versus6.4× raw32, bank conversion service. Reports: campaign/WEIGHT_REPRESENTATION.md and campaign/SHARED_CALIBRATABLE_ARITHMETIC.md. Raw32 calibration and quality remain conditional on ideal matched holders, numerator-only mismatch and a noiseless read reference; the actual differential two-holder FIA needs2kT/C rather than this model'skT/C. No physical system or SoTA claim.

### 2026-09-11 14:57 UTC — fresh-input sizing and architecture falsification

W0.50 fresh-amplitude SS85 failure confirmed by finer timestep. W0.70
fresh-amplitude control passes independently; actual N/P port screen
selects0.50/0.70 asymmetry for lowerwidth/offloading, now undergoing matched
fullscale/TT/finer tests. Couponlinearprojection included with explicit
scope and hashedsource. Population updated with group128 physical noise
failures, fixed-holder reuse radix risk, directFIA/splitDAC progress and
reference/noise-interface limits. Completed banktraces are being losslessly
archived; active simulations remain untouched.

### 2026-09-11 15:07 UTC — group128 physical budget rejected

Group128 Cu4 frozen differential2kT/C+50µV read-noise controls completed with both source audits passing. All16 physical cases failed KL, worst.0166854; worst PPL ratio1.0313277. Mismatch-only7/8 passed. The single-holder-reference raw32 controls remain live and conditional; they cannot be compared directly to the physical dual-holder FIA. Group64 differential control now calibrates against the actual N.50/P.70 TT four-bit bank table, preserving previous artifacts. An offline5%-per-bank calibration-proxy frontier reduces group128 ADC decisions12.50% and paid connected+reference C.964%, but requires new quality validation and does not rescue the noise failure. Grounded22-unit fixed-total and unequal low/high Cu sizing ledgers were recorded as conditional remedies, with holder matching, three-bit low-bank measurement and fullarray readout still unresolved. See campaign/WEIGHT_REPRESENTATION.md.

### 2026-09-11 15:20 UTC — signed-bank and readout progress

Selected asymmetricunsigned bank independently qualifiesSS85fresh inputs;
actual3-bit TT AC closes grounded28fF and bypasslow-bank loading. Shared
sign mux passes3-bit but fails4-bit charge gate; direct3TG/bit alternative
haslowerwidth/error/fixtureenergy buthigherinactiveC, nowunderverification.
All7 physical split-DAC weights and two carries measured; independent
calibratedcodecritic finds~2.21% quantizationvariance penalty at matched
coverage. Completecausal7-decision fineSAR is next, with actuallatchdecisions
and paidextendedhold/reset. Group64 noise-aware modelhasbothpassesandfailures;
no robust complete architecture winner. Prior failures and frozen sources
remain preserved.


### 2026-09-11 15:48 UTC — comparison checkpoint and continued falsification

Updated campaign/SESSION_COMPARISON.md against the starting sparse/dense
fixtures. Four fresh complete physical seven-bit SAR conversions pass
bounded deterministic checks; boundary-focused followups and independent
review assigned. Direct signed four-bit bank passes 1/0.5-ps comparison.
MIM coupon orientation gives TOP 0.10744% FAIL versus BOTTOM 0.08530% PASS
at 1 ps; finer runs active, no PEX/corner claim. L0.30/Cres3pF conditional
receiver noise remains 52.33 µV and misses 50 µV. Grounded G32 quality runs
continue. No complete SoTA or Mythic comparison has passed.


### 2026-09-11 15:57 UTC — signed transfer export and integration

Added measured-charge/admittance export with affine self-check. Exposed
SS signed coupon diagnostic affine calibration worsens residual to0.1423%FS;
TT3bit signed coupon passes initial1ps and exports actualcharge/loading.
Independent critic is implementing a4row physically floating grounded core,
including OFF share-switch mutual capacitance and explicit reset recurrence.
A constant-matrix correction suggests H≈A+2Cmutual for binary post-reset
radix; exact derivation independently agrees, physical verification pending.
New Wn.56/P.70 TOP-coupon transient launched using native admittance screen.
Seven completed bank traces losslessly archived:1,336,717,634bytes recovered.

- 2026-09-11 system research checkpoint: original raw32 source-audited48/48 conditional cases passed (32 physical-noise,16 mismatch-only), worst KL0.00331941/PPL ratio1.00626385. This retains unsigned old-TT loading, ideal radix and single-holder40µV model; not signed/dual-holder physical closure. Grounded G32 differential50µV jobs continue. Offline fixed-DAC early-stop ledger retains original C/Vref and clips while reducing comparator decisions9.495% for groundedG32 within each bank's5% calibration-proxy tolerance; no quality/energy/hardware claim. See campaign/WEIGHT_REPRESENTATION.md.


### 2026-09-11 16:06 UTC — unequal physical units and falsification

Unequal1.00/1.36µmMIM coupons passSubstrate2/Magic DRC/native matrix audit;
22-unit isolatedfootprint falls0.695% while conditional groundedG32 noise
variance falls8.71% by reallocating capacitance toward high-digit weight.
This is a conditional ledger, not a measured noise or macro improvement.
Signed4bit1260BOTTOM SS85 passes independent1/.5ps comparison; TOP.5ps
aborts numerically at146ns, separate.4ps control running. TT signed3/4tables
now export exactcharge separately fromloading. Small1um3bit SS passes1ps.
SAR frozenboundary calibration fails2/4 freshcases despite28/28 reproduced
physicaldecisions; consecutive large-to-small no-warmup histories now running.
Raw32 oldconditionalmodel finishes48/48PASS; stricter grounded and fixed-DAC
early-stop quality campaigns continue. No complete SoTA claim.


### 2026-09-11 16:14 UTC — physical sharing and continuous-readout limits

Connected4row signedgrounded core nominal TT passes independent20/10ps
product checks (fresh RMS~.02895MAC, max~.03446), but frozenTTcal atSS85
fails fresh max.28605MAC. Per-cornerfit passes; PVT tracking is not free.
Symmetricfresh coverage is expanding before timing optimization.
FIA seven-bit consecutiveword tests reproduce all physicaldecisions but
both history-invariance checks FAIL: nearthreshold target changescode63→64
versus independently initialized controls, despite unchanged acquiredinput.
Hidden latch dp/dn/tail states are being measured before a paidreset remedy.
TOP-column bank Wn.56/Wp.70 repairs initial1ps chargefailure but costs2.40%
more fixtureenergy than the passingBOTTOM Wn.50/Wp.70 point; finercontrol live.
Added independently configurable columnDC bias and launched±250mV column
controls to expose voltage-dependentloading outside the original.9V clamp.
2026-10-04: analog attention engine dropped. Blocks wta, rescale, softmax_combine, ptat_bias, translinear_softmax and their assembly deleted; attention scores/softmax/A·V moved to the digital rail; gain_cell_array kept for LoRA weights only. See docs/src/content/Project/APPLICATION_ATTENTION.md.

### 2026-10-04 — AnalogIOC phase 1c: digital top + behavioural macro + cocotb vs golden

`digital/analogioc/src/analogioc_top.v` (INTERFACE.md §7.4/§8): 17 tile_fsm joined by a
registered C-element, 17 datapath slices, abft_check, 16 requant, HI→LO pass sequencer,
LoRA writer, and the weight-load controller (wt_* row stream → w_wl/w_data, 2 clk/row,
overlapped with the previous pass's LO conversion). TT stub `src/analogioc.v` deleted.
tile_fsm: ota_en high in S_FINE, new col_exit. `analog/analogioc/va/analogioc_beh.v`
(bit-true to golden: stores what is written, eventrate_convert codes, protocol asserts,
JITTER) + blackbox `va/analogioc.v` + ports-only STUB `netlist/analogioc.spice`;
`macros.py check` → ports agree (37 signal ports, 5 supply pins).
cocotb (`build/verification`, `make`), all exact vs golden.model: A0; A11 96 passes
(272 cells × 6 patterns) + both assertions; A7/A12 the 11 compiler passes back to back,
JITTER 0 and 0.5 × 3 seeds (exposed write 0 ns after the first pass); relu fixture on all
11 passes; A8 on pass_04 (only a checksum-column LSB can flag there: clean 127 + data
|Δ| ≤ 17 < 199); E2E attn_o all 36 column tiles × 4 row tiles (144 passes) acc/residual/q
= golden proj. 10 iverilog tbs + `make synth` still pass; analogioc_top synthesizes with 0 latches.

### 2026-10-05 — phase 1d: weight_tile reprogrammable (INTERFACE §7)

weight_tile now stores its weights: every bank keeps all 4 bit caps, and each bit cap's
bottom plate sits on a selector (TG to the row, pull-down to vss) driven by a write-only 6T
bitcell. Writes go one row at a time through `wwl0..15`/`wd0..135` (16 WL buffers, 136
BL/BLB drivers). Ports: `xin_p_r0 xin_n_r0 .. xin_p_r15 xin_n_r15 col0..col16 wwl0..wwl15
wd0..wd135 phi1 phi1e phi2 vcm vdd vss`. One addition to §7.2: a per-bank code-zero gate
(st = phi2·(code≠0)). Without it, 32 idle 6 fF tops per column leak the OTA residual (a
lone W=13 bank read 63 %). Cell sizing: pull-down and access 0.42/0.15, pull-up 0.42/0.30
(the first step of a measured corner search; worst margin 561 mV vs 89 mV floor).
Measured on ESPice (ngspice agreed before the switch):
- write: all 15 corners pass. Worst row write is 986 ps at ss/−40 °C/1.62 V (2 ns budget).
- MC write yield: 200/200; margin 772 ± 19 mV.
- A11 readback: worst 1.79 LSB (gate 3).
- A11b/Q10 disturb: 0.004 LSB, so ping-pong is not needed. Re-check post-layout.
- Q13 write energy: 13.2 pJ/row with every bit toggling; 109 pJ/pass on random data (7.5 % of pass_energy_pj).
- t_q_floor: specs.c_row() is 101 fF (was 53), row RC 16 ps, so the floor stays 200 ps (jitter-bound). The measured row edge is 127 ps, which means pwm_driver's C_ROW = 100 fF has no margin left.
- k_cal was re-measured: 0.9747 (was 0.9906). The code-independent top costs 1.6 %.
- The DUT=va suite passes on ESPice (cascade included). On DUT=sch, tb_weight_tile and csnr pass on ESPice (one transient espice FileNotFound, which passed on rerun). The DUT=sch tb_cascade was **not run**: two attempts were killed, and the final rerun of cascade/weight_tile/csnr was stopped by request because the circuits are about to change. Everything is wired up and runnable via `make -C analog/weight_tile/build/sim test`.
- tb_weight_tile_mc null still fails, as it did before this change: σ 22 LSB, and the old deck gave 15. The cause is OTA offset, not the tile.
### 2026-10-05 — Phase 1b: lora_sidecar migrated; INTERFACE Q6 resolved

`analog/lora_sidecar/` (netlist, 4 Verilog-A child modules, tb_lora_sidecar / tb_lora_rho /
tb_lora_update / tb_lora_sidecar_mc), redesigned so the LoRA term matches
`golden.tile_mvm(lora=(A, B, rho))` with **signed x, signed A, signed B, both windows**:
always-on 2T cells (0.43/19.2 µm read device, I_cell = I_SIDE/16) with steered drains;
A pairs swapped by x_neg onto two integrators (Q_P − Q_N = A·x); XOR V→T window between
two latched comparators (delays cancel: x = 0 reads 0.000 code, no baseline pass);
B direct sinks (+) and biased PMOS mirrors (−); sign-magnitude 4b codes (W_MAX = 7);
HI window integrates one t_q per chop cycle. **rho measured: 0.01337 code per
(A_eff·B_eff·x) at sky130 tt/27 °C** (physical cross-check −1.6 %), recorded in
`analog/docs/lora_cal/sky130.json` (`specs.lora_cal()`); corner range 0.0054 … 0.0276
(per-chip calibration). vs golden: worst column 0.06 code LO, 0.06 HI, 0.23 HI at the
A·x budget (tol max(1 code, 5 %)); SGD step loss 175.6 → 11.5, |Δy − pred| ≤ 0.05 code;
61.6 pJ per LO op. ESPice and ngspice agree to ≤ 0.02 code (rho identical). Corners
3 × 15/15 PASS on ESPice. Remaining golden mismatch: the cell current is not linear in
the code (levels .0143 .0480 .1270 .2645 .4598 .7065 1 for m = 1..7; the 60 mV write DAC
cannot make 7 linear levels) — `golden.lora_quant` must quantize onto the measured level
table (exact change in the block doc; golden not edited). Analog top needs from
`tile_seq`: logic `xen<i>` (replaces the 16 xrd TG drivers) and `xneg<i>`.
Not yet run on ESPice for lora_sidecar (simulation paused by the user): the Monte Carlo
`tb_lora_sidecar_mc` (30 × tt_mm, written, never completed on either simulator) and the
gf180 hotswap. Done on ESPice: `make test` DUT=sch and DUT=va 3/3 PASS, corners 3 × 15/15.
### 2026-10-05 — phase 1a: integrator_conv migrated, conv_seq/tile_seq built (ESPice)

`integrator_conv` migrated to the INTERFACE.md §5 ports (35 pins, raw dual-rail comparator
outputs, no XSPICE state, bias as ports); `conv_seq` and `tile_seq` added to the async_ctrl
deck (static CMOS from that deck's cells). Converter change from AnalogIOC: both StrongARMs'
reference inputs are replicas of their signal inputs (the migrated, MC-sized strongarm
kicked the CDAC top −48 mV against hard vcm).
Run on ESPice (tt 27 °C, DUT=sch): tb_integrator_conv (A1) PASS, codes 0/15/16/−50/165 →
−1/15/16/−51/127, decisions = n_eval, E(0)/E(165) 0.14; tb_eventrate (A2) **FAIL**,
E(code 0)/mean 0.37 > 0.30: StrongARM 0.29 pJ/strobe vs origin ≈ 0.07 (fine phase 0.94 vs
0.27 pJ); tb_conv_seq PASS; tb_async_ctrl PASS (identical to ngspice). ESPice vs ngspice on
the converter: energies within 1.2 %, mac 16 reads 16 vs 15 (packet boundary, both ±1).
**Not yet run on ESPice** (simulation stopped by request; benches are wired and runnable):
tb_tile_seq after the join-reset / envelope-gap fixes (89d5591), tb_integrator_conv_mc,
all corners (integrator_conv, conv_seq, tile_seq), DUT=va for integrator_conv. See
analog/integrator_conv/docs/architecture.md and analog/async_ctrl/docs/architecture.md.


### 2026-10-05 — Phase 3: mixed-signal co-sim wired (not run)

`digital/analogioc/build/cosim/` runs `analogioc_top` inside ESPice as a VerA `.v` device
(`.hdl` + `N` card) next to the `analogioc` SPICE macro. This needs the least new code:
ESPice already provides the A2D (threshold `vth` = VDD/2) and the D2A (Thevenin `rout`
= 200 Ω, 150 ps ramps), and the two simulators share one transient. cocotb cannot drive
a device, and ESPice's C ABI cannot pause a transient to change a source. So the cocotb
Bench (weights streamed on `wt_*` ahead of the passes, cfg applied while idle) is
regenerated as Verilog from `pass_vectors.py`. Results come back out through
`obs_d[7:0]`/`obs_v` pins, and `cosim.py check` gates codes with ±CODE_TOL (8), the
residual ≤ budget, and prints the codes outside ±1. Ladder rails are B-sources of
`pkt_d` (span ∝ D, `specs.u_cal`/`fine_ref_trim`), biases are the contract origin values,
and `analog/analogioc/test/refs.json` overrides them when it exists.

- `make cosim-smoke`: **PASS**, 0.2 s (8 s on the first device build). A toy macro (RC +
  tanh comparators, no PDK) with 4 integ handshakes: col_sign == x_neg in every cycle,
  D2A 10–90 % 120 ps, and the req fall starts at v(integ_ack) = 0.95 V (vth 0.9).
- `make cosim-elab`: generates the 511-pin device and deck, then **stops in VerA**:
  E1100 (an `output reg` port on a part-select, in `tile_fsm`/`bacc_accum`). In a
  scratch copy with that rewritten, the only error left is E1103 (more than 256 pins).
  Under 256 pins the whole RTL passes `vera --check`. Filed as REQUIRED_TOOLING.md §4,
  together with a VerA panic on task enables, which `cosim.py` works around.
- Not covered by `check` yet: A9's "exactly 17 col_valid per window" and "RTL code ==
  codes decoded from the analog decisions". No beh protocol assertions exist on the SPICE
  side.

Run later, inside `./env.sh mixed`, once the real `analogioc.spice` lands and VerA §4.1–4.2 are closed:
```sh
cd digital/analogioc/build/cosim
make cosim-smoke                    # bridge sanity, seconds
make cosim-elab                     # must write out/cosim_dut.zig with no error
make cosim                          # A9: pass_05 (TSTOP = 12u per pass; set TSTOP=... on timeout)
make cosim PASSES="00 05 09"        # A12 co-sim: back to back

### 2026-10-05 — Phase 4: harden path wired (not run)

Nothing was simulated, laid out or hardened. The analog blocks → analogioc macro →
analogioc_top path is wired as make targets, and every cheap step was checked.
- **Layout route: hierarchical.** Each block in analogioc's `DEPENDS` gets its own verified
  layout and macro views, then `analog/analogioc/layout/analogioc.rs` (substrate2, **not
  written yet**) places them.
  - Flat Philis is out: the top has more than 20k devices flattened, against 45–60 min per
    iteration above 30 FETs.
  - Philis `--hier` is out: it cannot take `--interface`, and it writes pin text on 236/0.
  - `LAYOUT_ROUTE = gen` in `analog/analogioc/build/config.mk`, so `make pnr` there refuses.
- **Block layout Makefile** (template + all 13 copies): new targets `pnr-verify` (PDK klayout
  DRC + magic/netgen LVS on a Philis run), `views` and `deps`.
  - `views` writes `output/gds,lef/<b>.*` through `analog/common/layout/macro_views.py`. It
    renames bus bits `<i>` → `[i]`, checks every port has a metal pin and writes a bbox-OBS LEF.
  - `deps` runs `views` on every block in `DEPENDS`, deepest first.
  - Fixed in the schematic Makefile: `deps` called a `va` target that does not exist; it now calls `lint`.
- **Liberty:** `analog/analogioc/build/lib` (`make spec | lib | lib-interface`, `ACCURACY=spice` default).
  - `layout/liberty.py` builds the GPurify spec from `analogioc.ports` and writes it to
    `output/lib/liberty.json`. It is not committed: 0.8 MB, with a machine path.
  - Spec contents: 519 pins (415 in / 86 out / 13 analog biased at §2 values / 5 supplies,
    `vss` substrate) and no clock. 53 combinational handshake arcs: integ_req→integ_ack
    rise/fall, cmp_req[j]→cmp_ack[j] rise (dac 0 and 15) and fall, cb_ack[j]→cb_req[j].
    Corners tt_025C_1v80 / ss_100C_1v60 / ff_n40C_1v95, with the model path from `$PDK_ROOT`
    (GPurify expands no environment variables).
- **macros.py** (+ the .flows template): `lib` is now the `output/lib/` directory, mapped as
  `{"*_<corner>": [<b>__<corner>.lib]}`. A single file still maps to `"*"` (smoke unchanged).
  `min/` is skipped.
- **macros.toml:** explicit views, and the TODO is gone. `pg = []`, all 5 supplies in
  `analog_supplies`. The placement is a PLACEHOLDER (100, 100).
- **config.yaml:** the DIE_AREA is a PLACEHOLDER of 1500×1500. CLOCK_PERIOD = T_CLK_MAX = 20 ns.
- **Orchestration:** `make -C digital/analogioc flow` runs steps 1–5. `flow-package` is blocked (Q3).

Checked:
- `macros.py check`: ports agree, 37 signal ports and 5 supplies.
- The full chain ran on a fake 519-pin analogioc GDS: `macro_views.py` (519 pins, LEF), then
  `make lib-interface` (GPurify 0.1.0 accepts the spec; layout labels, LEF and reference
  ports all match; 3 corner libs), then `make config`. LibreLane 3.0.14's own config loader
  then accepted the result: it instantiated the Classic flow on the real `config.yaml` without
  running it. Every STA corner, nom/min/max × tt/ss/ff, picks the matching `analogioc__<corner>.lib`.
- The fake views were deleted and the generated block was left empty.

Open:
- `layout/analogioc.rs` is not written, and neither is the analogioc `interface.json`.
- Leaf generators exist for cmos_switch and strongarm only. A Philis GDS can't become views,
  because its pins are on 236/0.
- `gpurify` is not in the nix shell, and it needs ngspice.
- `spice` accuracy on the whole macro is days of runtime (REQUIRED_TOOLING §4–6).
- OpenSTA has to group the `x_mag[0]`-style scalar Liberty pins into buses. Check this at the
  first harden.

Run later, from `./env.sh mixed`:
```
make -C digital/analogioc flow-netlists     # VerA lint + netlists (deps, then analogioc)
make -C digital/analogioc flow-blocks       # = make -C analog/analogioc/build/layout deps
make -C digital/analogioc flow-top          # = make -C analog/analogioc/build/layout views
nix-shell -p ngspice --run 'make -C analog/analogioc/build/lib lib GPURIFY=... GPURIFY_DECK=.../pdks/sky130.deck'
#   (or lib-interface first: no simulation)
# set DIE_AREA (config.yaml) + location (macros.toml) from output/lef/analogioc.lef SIZE
make -C digital/analogioc flow-harden       # config + LibreLane harden + macros.py signoff
```

# Independent gm/ID checks for the logarithmic charge multiplier

Research date: 2026-09-10. **VERIFIED within the stated Sky130 DC/AC models:** the useful design variable is the ratio of actual exponential and diode-connected logarithmic slopes, not the nominal table gm/ID alone. Raising the physical reference current changes that ratio. **STRONGLY SUPPORTED as a local mechanism:** this can reduce multiplication error without changing the operand encoding. These checks do not establish a complete IMC architecture, novelty, noise performance, mismatch yield, or an advantage over Mythic.

The independent source is tb_imc_log_gmid.py. The physical transient multiplication and its measured energy belong to the separate log-charge probe and sizing sweep. This report derives and checks device behavior; it does not substitute its idealized charge calculation for those transistor-level transients. The [independent critic](IMC_LOG_PIPELINE_CRITIC.md) reviewed the charge conservation and derivative equations below.

## Reproduction and evidence

Run from the repository root with the cached Nix Python. The existing helper resolves pinned ngspice and the local Sky130A PDK. These commands need no shared-helper changes:

```sh
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_log_gmid.py
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_log_gmid.py --sized
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_log_gmid.py --candidate
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_log_gmid.py --reference
```

All four modes were run at TT/27°C and SS/85°C and printed `LOG GM/ID CHARACTERIZATION PASS`. The corresponding records are default, sized, candidate, and reference. They contain dimensions, actual bias values, deck hashes, and tool/deck locations; generated decks and raw `wrdata` files remain in `build/sim/imc_log_gmid*`. PASS means the explicit characterization checks passed, not that every proposed multiplier passed.

The default mode covers L={0.15,0.3,0.5,1}µm, W=0.42µm, nominal targets gm/ID={20,23,26,28}/V and a 1nA control. Each bias is evaluated at operand factors {2^-0.5,1,2^0.5}. The sizing tables were generated at TT, W=10µm and fixed VDS=0.9V. The fresh diode instances instead have VDS=VGS and the actual widths. SS uses the same physical currents and sizes selected at TT, not a separately retuned corner.

AC injects a small-signal current into an independent diode-connected replica and measures `Y=1/V`. At 1MHz, `Re(Y)` is checked against gm+gds and `Im(Y)/ω` gives the diode-port capacitance. A second diode replica drives the exp gate; subtracting the two admittances measures the exp gate port at fixed drain. Thus these C values include actual port responses, rather than substituting Cgg for every load. The tiny-signal AC source is a characterization fixture, not a proposed signal driver. There is no transient-noise or Monte Carlo run in this evidence.

## Why nominal gm/ID is insufficient

For a diode-connected input at current I,

\[
g_{\log}\equiv\frac{d\ln I}{dV}=\frac{g_m+g_{ds}}{I}.
\]

For an output transistor with fixed drain/source/body,

\[
g_{\exp}\equiv\frac{d\ln I_o}{dV_g}=\frac{g_m}{I_o}.
\]

With ideal unloaded voltage stacking, local product exponents are `gexp/glog_x` and `gexp/glog_y`. Matching table gm/ID values does not guarantee either exponent is one: the diode includes gds, the exp drain has a different bias, and narrow-width/PVT effects differ. A one-point gain calibration removes a multiplicative constant, not incorrect operand exponents.

The original W=0.42µm, L=1µm, I=1nA point gives actual diode gm/ID=24.2518/V and glog=24.5455/V at TT. SS gives 20.8065/V and 21.0694/V. A stiff-source 200fF load alone has the conditional 1% step times 37.75µs and 43.94µs. The actual sampled capacitor is between two finite-resistance diode nodes, which can be slower. A nominal 1nA log bias therefore does not support a 100ns acquisition assumption.

The table target 28/V is above the stored peak for L=0.3,0.5,1µm. Lookup clamps to a low-current endpoint, producing approximately 0.5pA in the narrow devices. The report explicitly flags these points as `table_target_above_peak`; they are **FAILED sizing targets**, not verified gm/ID=28 operating points. Leakage and numerical shunts matter at that current.

Narrowing only the exp transistor also failed as a robust slope fix:

| Input geometry/bias | Output W | TT unloaded exponent | SS unloaded exponent |
|---|---:|---:|---:|
| L0.3µm, W5.38µm, I1370.56nA | 5.38µm | 0.97850 | 0.98140 |
| Same input | 0.42µm | 0.93879 | 1.01982 |
| L0.3µm, W11.17µm, I263.07nA | 11.17µm | 0.97481 | 0.97649 |
| Same input | 0.42µm | 0.95962 | 1.09504 |

These are same-gate DC checks before sampling attenuation. Reducing exp gate capacitance trades against a substantial width- and corner-dependent slope error; global gain calibration cannot remove the latter.

## Frozen promising candidate: actual bias and curvature

The separately tested candidate uses all four core NMOS devices at L=0.5µm, W=1.86µm, operand current I=256.893nA, reference current κI=385.340nA with κ=1.5, and Cstate=600fF. The root transient fixture uses W=0.42µm/L=0.15µm transmission-gate devices and explicit nonoverlap. Its acquisition/evaluation sequence is independent evidence, not assumed in the DC measurements below.

| Quantity at operand factor one | TT/27°C | SS/85°C |
|---|---:|---:|
| Diode VGS=VDS | 0.564275V | 0.545124V |
| Actual diode gm/ID | 22.5328/V | 19.1228/V |
| Actual diode gds/ID | 0.17000/V | 0.14435/V |
| Diode logarithmic slope (gm+gds)/I | 22.7027/V | 19.2671/V |
| Diode tied-port capacitance at 1MHz | 3.5512fF | 3.5300fF |
| Exp gate Cgg at the same gate voltage | 3.9115fF | 3.8024fF |
| Actual exp gate-port capacitance at 1MHz | 4.8278fF | 4.7111fF |
| Exp gm/ID at the same gate voltage | 22.4743/V | 19.0861/V |
| Unloaded exponent before reference shift | 0.989940 | 0.990606 |

Curvature remains measurable across the input window:

| Corner | Operand factor | Input VGS | glog (/V) | Diode-port C (fF) |
|---|---:|---:|---:|---:|
| TT | 2^-0.5 | 0.549128 | 23.0537 | 3.4923 |
| TT | 2^0.5 | 0.579670 | 22.3137 | 3.6095 |
| SS | 2^-0.5 | 0.527240 | 19.4866 | 3.4761 |
| SS | 2^0.5 | 0.563228 | 19.0135 | 3.5835 |

Consequently a unity local exponent at the center is not proof of accuracy at the full window boundaries. The measured exp gate port exceeds model-reported Cgg by 0.91633fF at TT and 0.90872fF at SS; the difference is constant across these operand points, consistent with omitted overlap terms. This provides a quantitative warning against using Cgg alone for loading. Input signs, zero, exponent bits and a wider dynamic range are outside this scalar positive-mantissa experiment.

## Physical reference-current correction and residual asymmetry

Let `V(I)` be the actual diode inverse transfer and `Qp(V)` the exp gate charge at fixed output drain/source/body. Sampling sets the top to Vx=V(Ix) and the bottom to Vr=V(κI); evaluation releases the top and moves the bottom to Vy=V(Iy). With only Cstate and this gate charge,

\[
C(V_x-V_r)+Q_p(V_x)=C(V_g-V_y)+Q_p(V_g).
\]

The initial `Qp(Vx)` matters: the exp gate is already charged during sampling. Write `Cp(V)=dQp/dV`. Differentiating gives

\[
a_x=\frac{C+C_p(V_x)}{C+C_p(V_g)}\frac{g_{\exp}(V_g)}{g_{\log}(I_x)},\qquad
a_y=\frac{C}{C+C_p(V_g)}\frac{g_{\exp}(V_g)}{g_{\log}(I_y)}.
\]

The x and y coefficients differ even for equal log devices. Raising κ raises Vr and lowers the final Vg, moving the output to a larger gm/ID. This is a physical bias adjustment with a paid reference-current increase. No numerical power correction is applied to the output.

The `--reference` mode sweeps real standalone diode and exp devices on a 0.5mV voltage grid. It integrates the model-reported intrinsic exp Cgg to Qp, solves the scalar charge equation by interpolation, and checks both local exponents against finite differences. It contains **no ideal algebraic multiplier in SPICE**. Nevertheless, its charge equation is still a reduced numerical model: the extra measured gate overlap capacitance, TG charge, switch parasitics, noise, finite settling, layout parasitics and moving output drain are omitted. Those omissions make it a sizing diagnostic, not an independent physical multiplier validation.

For κ=1.5 and the frozen C600fF candidate:

| Reduced-model quantity | TT/27°C | SS/85°C |
|---|---:|---:|
| Reference diode Vr | 0.582314V | 0.566329V |
| Final gate from intrinsic charge conservation | 0.546352V | 0.524051V |
| Actual exp gm/ID at that gate | 22.8873/V | 19.3417/V |
| Local x exponent | 1.008333 | 1.004068 |
| Local y exponent | 1.001802 | 0.997745 |
| Exp current at x=y=1 | 180.227nA | 179.350nA |
| Largest absolute relative error on the 3×3 operand grid, after one-point gain calibration | 0.8299% | 0.6473% |

Minimizing `(ax−1)^2+(ay−1)^2` on κ∈[0.5,4] with 0.001 steps gives κ=1.339 at TT and 1.458 at SS. These are **local slope optima**, not full-window maximum-error optima or recommendations to replace the physically tested κ=1.5. The full circuit's switch charge can shift the optimum. At C200fF the earlier L0.3/W1.03 candidate has local κopt≈1.527/1.529 at TT/SS; L0.5/W1.94 gives 1.549/1.769. Reference tuning is therefore geometry-, capacitance- and corner-dependent.

## Acquisition time: two resistive diode nodes

During sampling, Cstate is between the input and reference diodes. Define Gx=gm_x+gds_x and Gr=gm_r+gds_r. Let Cx contain the measured input diode-port capacitance plus the measured exp gate-port capacitance; let Cr be the measured reference diode-port capacitance. Unlike the reduced intrinsic-charge calculation above, this acquisition calculation includes the extra measured gate overlap capacitance. The local linearized system is

\[
\mathbf C=\begin{bmatrix}C+C_x&-C\\-C&C+C_r\end{bmatrix},\qquad
\mathbf G=\operatorname{diag}(G_x,G_r),\qquad
\mathbf C\dot{\mathbf v}+\mathbf G\mathbf v=0.
\]

The slow time constant is `1/min(eig(C^-1 G))`. Neglecting small shunt caps, it approaches `C(1/Gx+1/Gr)`, rather than C/Gx. All eigenvalues were positive for the characterized points. With C600fF and κ=1.5:

| Corner/input factor | Slow local τ | ln(400)τ, a 0.25% local step criterion |
|---|---:|---:|
| TT, 2^-0.5 | 214.74ns | 1.2866µs |
| TT, 1 | 173.91ns | 1.0420µs |
| TT, 2^0.5 | 144.77ns | 0.8674µs |
| SS, 2^-0.5 | 253.31ns | 1.5177µs |
| SS, 1 | 204.52ns | 1.2254µs |
| SS, 2^0.5 | 169.83ns | 1.0175µs |

These are conditional local calculations, not measured full-scale acquisition times. Switch resistance, clock overlap, nonlinear large steps and required product accuracy change the actual limit. They explain why compressing acquisition near 1.5µs deserves an SS transient check, rather than assuming the table-derived TT target has already proved it.

Jointly scaling log and exp widths at fixed current density increases drive and parasitic capacitance together. For any simplified model `t≈α(Cfixed+W cΣ)/(g J_D W)`, the width-independent floor is `α cΣ/(g J_D)`. Increasing width cannot remove that floor. A full floor estimate requires the real capacitor network and switch parameters, not Cgg alone.

## Preserved negative result: the old long-acquisition abort

Both original C=1pF, acquisition=1ms decks aborted at time 0.016503s, with ngspice reporting `timestep too small`, step 6.25e-20s and trouble at `vsense#branch`. This equals fifteen 1.1002ms frame intervals. The old clocks simultaneously raised sample/bottom and lowered operate over the same 1ns boundary, creating a real possible overlap between the reference and y nodes. Completed old runs share that clock concern; convergence does not prove harmless overlap.

One isolated TT diagnostic moved operate OFF 38ns before the next frame and added an explicit final closing reset. It still aborted at the identical frame boundary. The diagnostic is preserved in its JSON record and `build/sim/imc_log_charge_abort_diag_nonoverlap_tt/`; the original evidence was not changed. Therefore removing that overlap was insufficient to resolve the abort. **The abort remains numerical nonconvergence, not evidence of a physical device failure.** Its exact numerical root cause was not established. New parent probes use their separately explicit nonoverlap schedule and do not inherit a claimed pass from this failed long run.

## What remains unverified

No thermal/flicker/shot-noise simulation, mismatch Monte Carlo, extracted layout, current-source circuit, programmable weight array, charge-to-log input conversion, output-drain compliance sweep, ADC integration or signed dot-product workload was run by this characterization. Only two global process/temperature combinations were examined. The intrinsic-gate model does not include switch charge or predict energy. The branch makes no novelty claim for logarithmic/translinear multiplication, gm/ID sizing, or reference-current bias adjustment; the [prior-art report](IMC_LOG_PIPELINE_PRIOR_ART.md) supplies that comparison boundary.

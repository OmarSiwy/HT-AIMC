# Independent review of the physical N4–FIA fixture

Status: **INDEPENDENT REVIEW COMPLETE; N1 passes declared deterministic gates, N4 fails fine co-gain and native reset.** This review
covers `analog/testbenches/tb_imc_fia_stack.py` and the frozen generated deck at
`build/campaign/fia_stack/n4_deckreview_r1`. It does not edit the author's files.

The crossed chain uses every physical segment exactly once, with alternating
polarity and two computational native banks. In the ideal equal-section case,
its differential signal gain isN; it does not create energy. Source initialization
occurs through actual TGs. Each FIA input reset opens before its series-stack
join closes. The closing sequence disconnects input join, disconnects crossed
links, restores bottom and top acquisition connections, then resets native
holders. No ideal analog-state copy or signal buffer was found.

The first-section12-bit host arithmetic is consistent:255Cu in coarse branches,
plus the series equivalent of4fF bridge and60fF fine total (=Cu=3.75fF), gives
256Cu=960fF. Subtracting that host from a1500fF N4 main section preserves its
nominal1500fF capacitance before declared physical parasitics. The finep0 charge
injection therefore has ideal native-equivalent step(Cu/16)ΔV/CA. The generator
compares its actual small-signal co-gain against the native calibration gain;
it does not refit a separate fine scale to force agreement.

MIM substrate parasitics are explicitly interpolated from contact coupons per
physical capacitor; MOS drawn geometry is included. This is a meaningful
parasitic model, but not routing extraction. Grounded coupon parasitics do not
bound mutual wiring coupling. All independent ideal source ports are included
in energy. Physical clock/reference generation, core arithmetic and complete
ADC sequencing are excluded.

Calibration uses the first two ±500µV native cases measured at97ns, before
acquisition opens at98ns. ±100µV and±20µV are held out; fine−1/0/+1 are tested
separately. Consequently gain absorbs repeatable release/loading effects, while
acquisition, held-input and amplifier-output checkpoints remain observable.
These cases are not a full12-bit ADC accuracy or noise demonstration.

## Reset and loading boundary

Both6pF banks represent computational holders. Their acquisition noise is to be
paid upstream, rather than declaring one a noiseless reference. Under independent
thermalization, each bank carries26.28µV RMS and their native differential carries
37.17µV atTT27. The20µV receiver budget can only exclude those modes when that
upstream allocation is explicit.

The separately reset FIA input load is a different mode. For an ideal N-section
stack and independently reset load CL,

sigma²_native,load = kT N² CL / CA².

This follows by dividing the load's transferred charge-noise variance by the
actual loaded signal gain, N/(1+N² CL/CA). As an illustration only, N4, CA6pF
and CL60fF give10.51µV extra per side, or14.87µV differential for independent
loads. A MOS gate's actual capacitance matrix, reset history, drain/source
correlations and subsequent FIA motion require a physical joint covariance
calculation. This illustration is neither a measured variance nor a proven
lower bound. It demonstrates why an active-FIA-plus-latch estimate alone is
incomplete for this connection, even though there is no explicit gate-holder
capacitor.

Native noise, load-reset noise and active device noise must each be propagated
once. Neither adding the fullkT/CL gate-voltage noise directly at the native
input nor omitting it entirely is correct. The earlier loaded-stack expression
already includes its declared native-plus-load modes; counting those again would
double count.

## Completed deterministic result review

The frozen source snapshot hash is
`7dd0239a615bc8094ec54a8cfdce31574cb66fc8bcbabb674871ca1d7b63c234`;
the N4 review deck hash is
`3e6b3f7a3489466a75f757c799b84b082f218bf0736fc0480180f091f1ab935d`.
Completed `n1_tt_r1` passes its declared fixture gates. `n4_tt_r1` fails fine
co-gain and native reset despite passing tested signs and native small-signal
linearity. N4 output gain is47.288743, compared with20.200530 for N1; this is
loaded deterministic gain, not a noise-qualified conversion-throughput result.

Independent phase analysis locates the fine error upstream of the FIA:

| Fixture | Native gain to FIA input at139ns | Fine gain at139ns | Fine/native co-gain at139ns | Output co-gain |
|---|---:|---:|---:|---:|
| N1 | .992387 | .966959 | .974377 | .975647 |
| N4 | 3.118861 | 2.877036 | .922464 | .925910 |

Thus a separate amplifier-gain calibration cannot repair the failed physical
fine/native charge relationship. At169ns, N4 input signal gain has fallen to
2.236805; this directly demonstrates substantial dynamic FIA loading. The
fine/native ratio remains.923684 there, consistent with its predominantly
pre-amplifier origin.

The worst N4 reset node is `n_t2` after the+500µV case. Its error decays
monotonically from−373.135µV at216ns through−148.132 at224ns and−60.280 at232ns
to−27.973µV at239ns. This is a late RC tail of roughly9ns, not an unexplained
static reset floor. A changed schedule or conductance still needs a fresh test;
no successful repair is assumed. Independent reset inspection also includes
native buses, intermediate bottoms and fine nodes, rather than only the
original top-node gate.

The fine-reset release at96ns produces about−1.824mV at the fine node and
−3.94µV at the first main section in the zero-input frame. At98ns the first
section still differs from its target by about−2.45µV. Native bus measurement
at97ns therefore does not characterize every section state. Much of this is
common mode and cancels in the tested differential signal, but the state must
remain visible in mismatch/history/noise work.

Independent numerical artifacts are under
`build/campaign/fia_stack_independent/`, separate from the author's run data.
The N4 interface remains **FAILED under its frozen gates**; none of these
findings is a complete ADC or IMC accuracy demonstration.

## Signal-precharged input-load hypothesis

Physically precharging the FIA input load from the same native signal, instead
of independently resetting it toVCM, can improve loaded signal gain. It must
use real connections and account for changed native loading. With Ce=CA/N²,
the ideal gain becomes( N Ce+CL)/(Ce+CL). A real separating switch does not,
however, guarantee perfectly correlated sample noise at its two terminals.

One explicit equilibrium covariance control writes

vA=e+q/CA, vL=e−q/CL,
Var(e)=kT/(CA+CL), Var(q)=kT CA CL/(CA+CL), Cov(e,q)=0.

The common and partition modes then give

Var(input-referred)=kT(CA/N²+CL)/(CA/N+CL)².

Relative to the same equilibrium stack with aVCM-reset load, RMS improves by
1/(1+N CL/CA). At N4/CA6pF/CL60fF this is only3.85%, rather than eliminating
load reset noise. Different upstream covariance must be propagated explicitly;
this equation is not a universal switched-MOS result.

A useful partial identity is
Varref/(kT/CA)=(1+N²r)/(1+Nr)², r=CL/CA. For N2 the first-order loading penalty
cancels, leaving(1+4r)/(1+2r)²=1−4r²/(1+2r)². This remains above the appropriate
kT/(CA+CL) total-capacitance floor and is not noise creation/cancellation for
free. A permanently attached gate can change which partition modes exist, but
then its physical capacitance and drain/source coupling participate directly
in computation and reconfiguration. The frozen N1/N4 runs do not implement
this variant.

## Output-hold and single-reference boundary audit

The new `tb_imc_fia_output_hold.py` has real TGs between FIA drains and the
existing250 fF storage nodes. Internal reset110ns occurs while storage is
isolated68.2--200ns; reconnection200ns permits a real reset before the next word.
The topology contains no ideal state copy. Its original `acquired_native_uV`
at29ns is the driven value before acquisition release, not the stored31ns
value. The stack branch added a separate31ns audit and preserved original gates.

The3.36um isolation fixture fails the original pre-isolation calibration gate;
its first-two-word post-isolation calibration is a legitimate diagnostic of
repeatable affine error, but does not erase the failure or validate an entire
fine SAR. Calibrating at119ns also does not establish accuracy at earlier fine
bit times, and only one latch event is present. The .84um alternative's
pre-isolation large-signal error shows why shrinking TGs is not free.

The single-ended variant physically removes the negative-side1 pF capacitor
and acquisition TG, replaces that input with a stiff VCM source, and doubles
the positive input stimulus to preserve differential amplitude. Its reference
port current/positive energy are counted; driver implementation and reference
noise remain unqualified. This correctly distinguishes one native kT/C holder
from the earlier two-holder differential fixture.

Independent raw-trace comparison at the20uV word (frame3):

| Fixture / checkpoint | Vip-0.9V (uV) | Vin-0.9V (uV) | Differential (uV) |
| --- | --- | --- | --- |
| Two holders,29ns |10.1874|-9.8127|20.0001|
| Two holders,31ns |-4436.2631|-4456.4814|20.2183|
| One holder,29ns |20.1814|approximately0|20.1814|
| One holder,31ns |-4419.4608|approximately0|-4419.4608|

The approximately-4.44mV acquisition-release shift was common mode in the
two-holder fixture and becomes differential against a stiff reference. It
appears before FIA amplification starts40ns. Therefore this single-ended
failure is evidence of uncompensated acquisition injection, not proof that a
single-ended FIA architecture is impossible. A reference offset or dummy
compensation would require physical implementation and frozen calibration;
post-conversion digital offset subtraction cannot restore lost analog headroom
or repair comparator decisions that were never centered on the intended residue.
Actual IMC-native acquisition may have a different charge boundary from this
voltage-source/TG fixture and must be tested directly.

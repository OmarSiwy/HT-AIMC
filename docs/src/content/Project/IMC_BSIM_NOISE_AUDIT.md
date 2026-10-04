# Native BSIM4.5 versus 4.8 noise: bounded source audit

2026-09-09. This audit reads the exact ngspice-43 source and existing stationary
noise artifacts. It runs no simulation and changes no model. The electrical
DC/charge agreement already measured does not establish noise equivalence.

## Specific active equation difference

The explicit TT cards use `tnoimod=1`, `fnoimod=1`, `rdsmod=0`,
`rbodymod=1`, `rgatemod=0`, and `igcmod=igbmod=0`. Their selected models are
NFET bin 26, W/L=3.5/0.15 µm, and PFET bin 35, W/L=2.25/0.15 µm, both nf=1.
The instance cards explicitly set nrs=nrd=0.
[Extracted coefficients and geometry](../../../../build/research/imc_flat_model_tt_27.json).

For the normally oriented transistor, define `G=sourceConductance`,
`D=IdovVds`, and `a=theta² G/D`. Legacy BSIM4.5 assigns the source thermal
noise conductance `G/(1+a)`; BSIM4.8 assigns `G(1+a)`. Their source-current PSD
ratio is therefore `(1+a)²` **if the internal state and theta agree**. The
corresponding reverse-oriented branch is the drain. This is a noise-source
coefficient; neither expression replaces the electrical conductance in the
DC/AC matrix.
[Legacy source, lines 160–188](../../../../build/research/ngspice43_native_prune/source-stock/src/spicelib/devices/bsim4v5/b4v5noi.c),
[4.8 source, lines 185–215](../../../../build/research/ngspice43_native_prune/source-stock/src/spicelib/devices/bsim4/b4noi.c).

Both native implementations force internal source/drain nodes when this noise
mode is requested. With the explicit zero source/drain squares, they substitute
1000 S conductances for the zero resistance. The existing noise logs contain
the corresponding warnings. Thus zero drawn access resistance does **not**
remove this noise-partition branch in the present test.
[Legacy node creation](../../../../build/research/ngspice43_native_prune/source-stock/src/spicelib/devices/bsim4v5/b4v5set.c),
[Legacy conductance handling, lines 1613–1673](../../../../build/research/ngspice43_native_prune/source-stock/src/spicelib/devices/bsim4v5/b4v5temp.c),
[Existing TT run](../../../../build/sim/imc_bsim_revision_noise_tt_27).

BSIM4.8 additionally clamps theta to 0.9 and to 0.9 beta. Neither clamp exists
in the legacy branch. For these TT coefficients, PMOS theta is always 0.34
because tnoib=0, whereas beta≥0.69 for positive effective length. Both PMOS
clamps are therefore inactive. For NMOS, tnoia=15e6 exceeds tnoib=9.9e6,
so theta/beta≤0.26/0.94≈0.277: its relative clamp is also inactive. Its
absolute 0.9 clamp can activate at sufficiently large
`(Vgsteff/EsatL)²`; the saved total spectra do not expose this internal value.

The active intrinsic channel-noise formula is otherwise the same:
`4 k T m { [beta(gm+gmbs)+gds]² − theta²(gm+gmbs+gds)² } / D`.
Consequently the theta clamp can also change channel noise when it activates.
The default floor on D is 1e-9 in both implementations. After normalizing
device-name prefixes, the complete native flicker helper differs only in an
irrelevant initialization of T0; the active fnoiMod=1 interpolation has the
same algebra. The active five-body-resistor source formulas also match.
Gate-resistor and gate-shot noise are disabled by these cards. The newer
correlated-gate mode is tnoiMod=2 and is not active here.

## What the existing spectra establish

At gate drive 0.5 V and target drain bias 0.1 V, the recorded total output PSD
ratios are:

| Corner/device | 4.8/4.5 at 1 MHz | 4.8/4.5 at 1 GHz |
|---|---:|---:|
| TT 27°C NFET | 1.069610 | 1.185796 |
| TT 27°C PFET | 1.274522 | 2.430434 |
| SS 85°C NFET | 1.062851 | 1.138382 |
| SS 85°C PFET | 1.273283 | 1.596058 |

The absolute difference is nearly constant through MHz, then increases with
frequency. A descriptive `A+B(f/1 GHz)²` fit to the existing 1 Hz–1 GHz data
has maximum residual below 2.5e-7 of the 1 GHz difference in all four cases.
For TT, A is 2.943324e-27/1.195137e-27 V²/Hz for N/P and B is
3.758562e-27/4.906945e-27 V²/Hz. This strongly supports a changed white source
coupling through both conductances and capacitances. It does not independently
measure the source contribution or establish that other internal quantities
are equal. The output uses a noiseless 1 S drain load; it is not a comparator.
[Reanalysis and source hashes](../../../../build/research/imc_bsim_noise_source_audit.json),
[TT stationary sweep](../../../../build/research/imc_bsim_revision_noise_tt_27.json),
[SS stationary sweep](../../../../build/research/imc_bsim_revision_noise_ss_85.json).

The large GHz PMOS discrepancy is therefore not explained by a theta clamp,
nor can its 2.43 ratio be used as a broadband correction factor. Its square
root, 1.559, is only the amplitude-density ratio at that sampled frequency;
it is not an integrated RMS or clocked decision-noise ratio.

## Bounded qualification path

First qualify the VA implementation against **native 4.8**, with the exact
flat coefficients, before trying to reproduce legacy noise. The supplied VA
noise block implements the newer multiplication and clamps. A separate
upstream translation issue also exists: the manual Gm/Gmb/Gds calculation
omits three Gm chain-rule terms at lines 7365–7367 and a fourth term in
dvs_dVg at line 7377. These manual derivatives feed tnoiMod=1 even when
automatic differentiation keeps the external DC current correct. The fourth
term lies in the vtl>0 branch, inactive for these explicit cards. The reviewer
is testing an isolated correction; this audit does not modify the VA source.
[Unmodified VA source](../../../../build/research/transient_noise/src/vacask/devices/spice/bsim4v8.va),
[Native derivative equations, lines 2119–2137](../../../../build/research/ngspice43_native_prune/source-stock/src/spicelib/devices/bsim4/b4ld.c).

After that gate, the smallest defensible legacy experiment is a separate,
explicitly named research model selecting the legacy tnoiMod=1 equations:
restore division on the selected source/drain branch and omit both theta
clamps, preserving every electrical and other noise equation. This would be a
4.8 electrical model with a legacy-noise option, **not** a complete BSIM4.5
port. Preserve the unmodified 4.8 result as a control and retain all raw model
coefficients, including lintnoi, whose legacy showmod getter is missing.

Before any clocked-latch conclusion, compare individual rd/rs/id/body/flicker
contributions and their sum against native 4.5 over the existing nine static
biases at each corner. Also check the internal values used by the noise
equations, derivative consistency, negative VDS and relevant body-bias
conditions. No scalar PSD rescaling or switch to tnoiMod=0 can substitute for
this attribution. A mismatch must stay visible rather than be absorbed into
fitted noise coefficients.

Only after device and deterministic latch comparisons pass should the
clocked experiment measure decision probability versus input, with explicit
noise bandwidth/step convergence, initialization, seed statistics and reset
history. Existing total stationary spectra leave those quantities, model
mismatch across other device sizes, and actual comparator input-referred
temporal noise unresolved. Neither revision is proven to represent measured
Sky130 silicon noise by these software comparisons alone.

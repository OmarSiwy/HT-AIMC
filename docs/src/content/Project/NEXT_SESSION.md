# AnalogIOC optimization — session 2 handoff

**Goal: MAXIMIZE tok/s vs Etched Sohu AND improved tok/J.**

## Read first, in order

1. `docs/src/content/Project/OPTIMIZATION_RESULTS.md` — the consolidated scorecard from
   session 1 (start here; labels every result measured/derived/projected).
2. Backing analyses: `CASCADE.md`, `SERVO_EG.md`, `SOHU_VERIFIED.md`,
   `ERROR_IMPACT.md`, `METRICS.md`,
   `COMPOSED_RESULTS.md`, `VERTICAL_3D.md`, `MOE_MAPPING.md`.
3. `AGENTS.md` + `CONTRACT.md` for conventions; `analog/schematics/specs.py`
   for the laws.

## Where session 1 left it (settled — do NOT re-derive)

- tok/s is at **0.97× (series cascade) → 1.20× (parallel super-tile,
  SPICE-verified)**. **2× is NOT reachable by scheduling/topology** — the
  random √K SNR term caps FFN at K=9 (SNRs≈38 dB), and the gain servo is
  Pelgrom-floored. Per-layer K, parallel super-tile, servo-eg are **exhausted**.
- **The joint binding constraint on BOTH goals is conversions/token.** Each
  conversion costs time (tok/s) and energy — and **83% of pass energy is OTA
  _static_ burn set by conversion time**. Fewer conversions/token ⇒ deeper K ⇒
  both faster and lower energy.
- Deeper K (K=7→14, the 1.95× crossover) requires **raising source
  compute-SNR to ≥44 dB** (currently 34–38). That is the real lever, and it is
  **unexplored**.

## Mandate for session 2 — attack SNRs and OTA static power, NOT scheduling

1. **Raise source SNRs** (unlocks deeper K → _both_ 2× tok/s and fewer
   conversions = better tok/J). Characterize each in SPICE, quantify
   dB-gained → K-allowed → tok/s & tok/J at N4/7B:
   - Fix the **multi-bank OTA charge-transfer deficit** (currently ~84%
     delivery on the shared rail — caps effective SNR _and_ accuracy). A
     higher-gain / faster OTA is the most direct win.
   - Larger **C_int** (kT/C floor) — trade vs area/energy.
   - **Correlated double sampling / chopping** to cancel systematic error.
   - **Bit-slicing / "spend devices" for SNR** (note 27c9) — area not energy.

2. **Cut the 83% OTA static burn directly** (pure tok/J, maybe tok/s):
   class-AB or **duty-cycled / gated OTA bias** so it only burns during
   settle; gm/ID re-optimization. Single biggest untouched tok/J lever.

3. **LVT (low-Vt) devices — candidate, with a real tension (user idea).**
   sky130 has lvt/hvt flavors. LVT raises gm/ID and speeds settling → helps
   the OTA static-burn + settle-time axis (tok/s + tok/J). BUT it **lowers the
   usable signal range / V_swing**, which _directly hurts SNR_ (SNR ∝
   V_swing²·C/kT) — and raises leakage (could worsen static burn unless
   duty-cycled). So LVT trades the SNR/swing axis against the speed/gm axis.
   **Quantify the net**: does a faster/cheaper LVT OTA outweigh the swing-loss
   SNR hit for the conversions/token goal? Possibly LVT on the _OTA/logic_
   (speed) + keep the _charge/signal path_ at nominal-Vt (swing). Worth a
   focused SPICE study before committing.

4. **Re-run** `compose.py` / `perlayer_k.py` / `pdk_projections.py` with the
   new SNRs/OTA to see if 2× tok/s + better tok/J actually lands, honestly.

## Guardrails (learned the hard way in session 1)

- **ONE analog sim-driver at a time.** `systemd-oomd` (PID 1425) SIGTERMs
  (rc=−15) any concurrent heavy ngspice. Compiler/analysis agents can run in
  parallel; analog sims cannot. If you see rc=−15, it's a sim collision, not a
  bug — serialize.
- Env: python `/nix/store/…python3.13…env/bin/python3`,
  `PYTHONPATH=<repo root>`; ngspice `build/ngspice43`; PDK `~/.volare/sky130A`.
- **Label every number measured / derived / projected. Correct overclaims
  loudly.** Session 1's value was catching its own: 2× tok/s, −33% CSD,
  ±1 LSB accuracy, and the count-INL theory were all wrong. Verify claims in
  SPICE; check whether a problem needs fixing _before_ building the fix (the
  #24 model-adequacy pattern — the model tolerates ±8 LSB, so don't chase ±1).
- Default paths stay byte-identical (opt-in flags); preserve A7/A8/A11 anchors
  - `specs.py` K=1 self-check; commit per green result.

## Workflow that worked

Spawn focused background agents with strict file ownership (analog/ vs
compiler+scripts/golden/ vs docs), one analog sim-driver, coordinator commits each
green result and reconciles shared docs (CASCADE/METRICS/RESULTS3/STATUS are
coordinator-owned to avoid write races). Use research agents for load-bearing
uncertainties (Sohu numbers, device feasibility). Read
`OPTIMIZATION_RESULTS.md`, then propose the SNR-raising + OTA-static + LVT plan
BEFORE spawning agents.

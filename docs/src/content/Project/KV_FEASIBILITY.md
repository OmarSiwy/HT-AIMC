# KV Feasibility Gate for Chip 2 (in-memory analog attention engine)

Two physics questions decide whether the KV cache can live in analog gain cells
on Chip 2 with **no HBM in the attention path**:

- **Q1** — Do the attention MACs (qKᵀ and A·V) *consume* the stored KV?
- **Q2** — Is leakage low enough to hold KV uncorrupted long enough, and what refresh does it cost?

Verdict up front: **GO.** Reads are non-destructive (**−4.3 µV/read**, cumulative);
retention to first-LSB corruption is **~1.7 ms refresh-free** (τ = 27 ms, 4-bit law),
closed by refresh-from-shadow. Caveats: session length forces refresh, and τ is
temperature- and technology-dependent (Si logic ~ms; IGZO/BEOL ~seconds+).

Sources: repo measured data (`tb_gain_cell.py`, STATUS A3, CHIP2_SPEC), research
notes 27i6 / 27l2 / 27l10 / 27i3 / 27h7, and analog-IMC literature (Leroux 2024,
Feng 2026, imec/IEEE IGZO 2T0C DRAM).

---

## Q1 — Non-destructive? YES.

### Mechanism (the 2T decoupled read)

A 2T gain cell separates *store* from *read*. In `gain_cell_array.py`:

- `Xw wdata wsel store` — write switch onto the isolated storage node.
- `Cs store vss 30f` — the MOM storage cap.
- `Xr col store rd` — the **read device whose *gate* is on `store`**.

Because the read transistor senses the stored charge through its **gate**, the
read current is drawn **from the column rail / read source line, not from the
storage cap** (note 27i6: "the read device M_R has its *gate* on S, so reading
draws no charge from the storage node at all — the read current comes from the
supply, and the cell provides gain rather than dividing charge"). The stored
value is only gate-coupled; the multiply is a transconductance sense, not a
charge dump. Contrast a 1T1C DRAM cell, which reads by dumping charge onto the
bitline and must write back — destructive by construction. This gate isolation
is the enabling property for a parallel in-memory MAC: many rows read at once,
none loses state.

### Why this differs from the weight-tile read (resolving the "no third chip" remark)

`THE_COMPILER_STRUCTURE.md` Part IV says analog IMC reads are **consuming for
weights** but survivable for KV. That is not a contradiction — it is two
different substrates:

- **Weight tile = charge-domain capacitive MVM.** The multiply *is* charge
  redistribution: the stored charge on the tile caps is steered/shared onto the
  integration node every operation (note 27i3: a capacitive cell dissipates
  `α·C·V²` **per transition** and its state moves during the op). The read
  *is* the perturbation; the stored value is the operand being redistributed.
  Reading disturbs it, and power-loss erases it — fatal for a value that must
  live the model's whole deployment. Hence weights keep HBM backing and there
  is no third chip.
- **KV gain cell = gate-sensed current.** The storage node is behind an off
  write-switch and is only read *through a gate*. No stored charge leaves the
  cap during qKᵀ or A·V. The read is gain, not redistribution.

The second half of the asymmetry is *lifetime*: a KV entry is written fresh
every request and read a **bounded** number of times inside its attention
window (note 27i6's τ > 2ᵇ·T_use law is *about* this), whereas a weight must be
read-only-persistent forever. A consuming read is intolerable for the latter and
survivable for the former even if it weren't perfectly non-destructive — and
here it *is* effectively non-destructive.

### Measured drift per read (repo, `tb_gain_cell.py`, live run)

- **10 read pulses (100 ns each, level 13 = 780 mV victim) shift storage by −42.8 µV → −4.3 µV/read.**
- 10th read still delivers full current (2.041 µA) — reads stay alive.
- Write-disturb from a neighbouring-column write (opposite data) = **−6.2 µV**, < 1 LSB.
- 1 LSB (write DAC) = 60 mV. So one read is **~1/14,000 of an LSB**.

### Cumulative-disturb math over a KV entry's read count

Read pattern (CHIP2_SPEC §2.2): d_h = 128 stored as 16 sub-banks × 8 rows. Each
query reads a token's **K** entry once (qKᵀ) and its **V** entry once (A·V). Over
a residency window of W tokens, an entry is read by each subsequent query:
worst case ~W K-reads and ~W V-reads.

Total read-disturb over W reads = W × 4.3 µV. To stay under 1 LSB (60 mV):

    W_max ≈ 60 mV / 4.3 µV ≈ 14,000 reads.

So even a **W ≈ 2048-token residency window** (target scale, CHIP2_SPEC §2.1)
costs ≤ 2048 × 4.3 µV ≈ **8.8 mV of read-disturb — well under 1 LSB (60 mV)**,
and this drift is *systematic single-polarity*, absorbable by the code→I
calibration. Read-disturb is **not** the binding constraint; leakage (Q2) is.
(Repo test T6 `tb_kv_residency` guards exactly this: ≤ 50 µV per 10 reads over
100 passes + a refresh cycle.)

### Literature confirmation (a)

- **Leroux 2024** (Nature Comp. Sci. s43588-025-00854-1 / arXiv 2409.19315):
  gain-cell crossbar simultaneously stores the KV cache and computes attention;
  a dedicated read transistor generates current from the cap voltage so **"unlike
  DRAM, this enables non-destructive read operations, supporting highly parallel
  IMC computations."** 1.5B-param model, up to ~70,000× energy and ~100× speed
  vs GPU (for the modified attention path).
- **IGZO 2T0C DRAM** (imec; IEEE 10019435): 2T0C cells "offer non-destructive
  read operations" — same 2T gate-decoupled principle in a BEOL oxide-semiconductor
  process.

**Q1 verdict: NON-DESTRUCTIVE.** Mechanism = 2T gate-decoupled read (no charge
leaves the storage cap); measured **−4.3 µV/read**; cumulative disturb over a
2048-read window ≈ 8.8 mV ≪ 60 mV LSB; confirmed by Leroux 2024 and the IGZO
2T0C line. Chip 2's "KV in analog" premise survives Q1.

---

## Q2 — Retention long enough? YES with mandatory refresh.

### Measured retention (repo, `tb_gain_cell.py` live run)

- Store 780 mV, droop over 3.30 µs = **+92.8 µV** → **τ ≈ 27.2 ms** (linear
  extrapolation V₀/droop-rate; STATUS A3 quotes ~27 ms).
- Note: the 2T all-NMOS cell uses a **long-L write switch specifically for
  retention** (subthreshold + GIDL leakage on the store node is what sets τ).

### Retention to first-LSB corruption (the τ > 2ᵇ·T_use law, note 27i6 / CHIP2_SPEC §2.1)

Requiring decay over the use interval to stay under 1 LSB (2⁻ᵇ) gives
**τ > 2ᵇ·T_use**. KV is stored at **b = 4 bits**, so the refresh-free residency is:

    T_res(1-LSB) ≤ τ / 2ᵇ = 27 ms / 16 ≈ **1.7 ms.**

That is the retention time to first-LSB corruption for a 4-bit KV element. Any
real decode session (seconds to minutes) outlives 1.7 ms by orders of magnitude,
so **refresh is mandatory**, not optional.

### Refresh scheme + cost (refresh-from-shadow)

The digital shadow copy of KV exists anyway (for spill / the B8 sink SRAM
island), so refresh = **rewrite each entry from its shadow at τ/2 cadence**
(no read-back-and-restore, no accumulated analog error):

- Cadence: τ/2 ≈ **13.5 ms**.
- Energy (W_res = 2048, d_h = 128, K+V = 2·262k cells) at measured
  E_wr = 7.5 fJ/cell = 3.9 µJ per full rewrite / 13.5 ms ≈ **~0.3 mW per head**.
- Time: 150 ns column write slot × 2048 columns = 307 µs per array per 13.5 ms
  = **~2.3% write duty** (projected). Refresh writes serialize against reads on
  the wsel/wdata buses → sequencer must interleave (open risk R4).

Read-disturb (Q1) and leakage add, but leakage dominates: 1.7 ms leakage budget
vs the 8.8 mV read-disturb over a full window means the refresh cadence set by
leakage already covers read-disturb with margin.

### Technology lever (Si vs IGZO/BEOL) and temperature caveat

- **τ is exponential in temperature** (note 27i6 "when it breaks": subthreshold
  leakage is exponential in T; a hot die shrinks τ, tightening T_res and the
  refresh cadence). The repo softmax already shows a hot-die drift path
  (β(T)); the same physics shortens KV retention. **The 27 ms is a room-temp
  number** — budget refresh cadence against the worst-case junction temperature.
- **Escape hatch for long/idle sessions: BEOL oxide-semiconductor (IGZO) gain
  cells.** Wide-bandgap IGZO has extremely low off-current → orders-of-magnitude
  longer retention:
  - Leroux 2024: OS gain cells project **~3 orders longer** τ than Si CMOS.
  - imec: capacitor-less IGZO 2T0C DRAM **>400 s retention**; **>10³ s** with
    >10¹¹ endurance (researchgate 359127289).
  - IEEE 10019435: **10 ks @ RT, 7 ks @ 85 °C**, sub-10 ns speed, 3-bit.
  This drops refresh from ms-class (kHz cadence) to **Hz-class or below** — the
  right substrate for multi-hour parked sessions (note 27l2: the residency win
  is largest exactly where a session sits idle holding state). **Not available
  in sky130** — document as a production/technology option, not this tape-out.

### Literature confirmation (b)

- **Leroux 2024**: silicon CMOS gain-cell **τ = 5 ms** (28 nm PDK); OS devices
  orders longer. The repo's **27 ms** (sky130) is ~5× better than Leroux's Si
  number — the long-L write switch pays off — but same regime and same law.
- **imec / IEEE IGZO 2T0C**: ms-class Si vs seconds-to-ks IGZO confirms the
  technology lever quantitatively.

**Q2 verdict:** retention-to-1-LSB-corruption = **~1.7 ms** (τ = 27 ms / 2⁴).
Refresh-from-shadow at τ/2 ≈ 13.5 ms closes it at **~0.3 mW/head, ~2.3% write
duty**. Temperature shortens τ; IGZO/BEOL is the lever (seconds–ks) if sessions
or thermals demand it.

---

## Overall GO / NO-GO for "KV stays in analog, no HBM"

### GO.

Both physics gates pass on measured sky130 data and are corroborated by the
analog-IMC literature:

- **Q1:** reads are non-destructive (2T gate-decoupled), −4.3 µV/read, cumulative
  disturb ≪ 1 LSB over a full residency window. The consuming-read problem that
  kills a weights-in-memory "third chip" (charge-domain redistribution) **does
  not apply** to gate-sensed gain cells with bounded lifetime.
- **Q2:** 1.7 ms refresh-free at 4 bits, closed by refresh-from-shadow that reuses
  the digital shadow already present for spill, at ~0.3 mW/head.

### Honest caveats that shape the build plan

1. **Refresh is load-bearing, not optional.** The "no HBM in the *attention
   path*" claim holds, but a **digital shadow of KV** must exist (host/SRAM
   island B8) and be rewritten every ~13.5 ms. A missed refresh silently
   degrades stored bits rather than faulting — the sequencer must guarantee the
   refresh/read interleave (risk R4). This is a *shadow*, not the HBM streaming
   the two-chip cut was built to kill; the interconnect still carries only
   O(d_h) messages.
2. **Temperature.** 27 ms is room-temp; a hot die shrinks τ and tightens the
   refresh cadence. Budget cadence at worst-case T_j; leave a trim knob.
3. **Session length / technology.** Si logic gain cells (ms τ) are fine for
   active decode with refresh. Long-idle / parked sessions (minutes–hours) want
   **IGZO/BEOL** (seconds–ks τ, Hz-class refresh) — a production-node option,
   not this tape-out.
4. **Noise is non-uniform (does not change GO, changes accuracy plan).** Note
   27l10 / Feng 2026: zero-mean analog KV noise *flattens* softmax and hits
   sink + recent tokens hardest (perplexity 11.06 → 33.91 unprotected). Fix is
   already in the spec: pin the **B8 digital sink+recent set** (index-only
   policy, ~3% energy) and keep the bulk on analog. This is an accuracy caveat,
   not a feasibility blocker.

**Bottom line:** the "KV lives in analog, no HBM in the attention path" premise
is physically sound. Build it, with refresh-from-shadow as a first-class,
sequenced subsystem and a temperature/technology margin on the refresh cadence.

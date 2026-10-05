"""2T gain-cell KV array (8x8) — topology + sizing. Prints the bare .subckt deck.

Ported device-for-device from AnalogIOC components/gain_cell_array. Cell (all-NMOS, no
vdd rail): write switch `w` (wdata -> store, gate wsel), storage cap `s` (store -> vss),
read device `r` (col -> rd, gate = store). One token = one column: raise wsel<c>, drive
the row-shared wdata<r>. Read = PWM row pass: rd<r> idles at VCM (read device off) and
is pulled to 0 for the PWM time; every cell of the row sinks I_read(store) from its
column rail, held at VCM by the tile integrators. Storage range [0, V_W] (V_W =
cmos_switch.v_write(), AnalogIOC's 0.9 V write ceiling for an NMOS-only switch), written by
a 4b DAC: LSB = V_W / 15.

Sizing (spec: analog/gain_cell_array/docs/architecture.md):
  store  c_store from specs.design() (30 fF); MIM, AnalogIOC's ideal C.
  write  triode switch (no gm/ID coordinate), two budgets from the AnalogIOC write path:
         R_on(V_W) <= cmos_switch.R_GUARD * cmos_switch.r_on_budget() (store settles to
         B_Y bits in the 100 ns write slot) and I_off(|VDS| = V_W) <= LEAK_GUARD * the
         leakage that droops the store 1 LSB over HOLD read intervals. Both are measured
         on every corner x temperature with the PDK's own models (switch_char(), cached
         in netlist/char/<pdk>.json): at V_W with the gate at VDD the NMOS sits near
         threshold (body effect), so R_on has no closed form. L is stepped up in Lmin
         until the width that meets R_on also meets the leakage budget (AnalogIOC picked
         L = 0.5 um for retention by hand).
  read   gm/ID coordinate fixed by the write ceiling: full scale is VGS = V_W at
         VDS = VCM (rd = 0, col = VCM — the gm/ID tables' own mid-VDS slice). Full-scale
         current = specs.I_SIDE, the column OTA's class-A sink (AnalogIOC: ~10 uA measured
         at its 10 uA/side bias), so W = I_SIDE / J_D(VGS=V_W, L); W below min_w would
         overshoot that ceiling, so such L are skipped. L is stepped up until the
         MEASURED sigma(VGS) (docs/mismatch.py) at mid and full scale keeps 3 sigma under
         LSB/2 with VOS_SHARE of the variance (the rest: write-switch injection mismatch).
"""
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "cmos_switch" / "netlist")]
import cmos_switch as sw  # noqa: E402
import gmid  # noqa: E402
import mismatch  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, mim_cap  # noqa: E402
from pdk_char import ngspice  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

ROWS = COLS = 8          # d_head = 8 rows x 8 tokens (AnalogIOC)
CELL_PORTS = ["wdata", "wsel", "rd", "col", "vss"]
LEVELS = 16              # 4b write DAC
T_READ = 2 * 16 * specs.TQ_SIM   # full INT8 PWM read: two 16-slot nibbles (320 ns)
HOLD = 10                # retention: < 1 LSB droop over HOLD read intervals (AnalogIOC tb)
LEAK_GUARD = 0.5         # of that droop allotted to worst-corner switch leakage
VOS_SHARE = 0.9          # of the read-error variance allotted to the read device
K_MAX = 40               # L search limit, in Lmin
CHAR = Path(__file__).resolve().parent / "char"


def ports(rows=ROWS, cols=COLS):
    return ([f"wdata{r}" for r in range(rows)] + [f"wsel{c}" for c in range(cols)]
            + [f"rd{r}" for r in range(rows)] + [f"col{c}" for c in range(cols)] + ["vss"])


PORTS = ports()


def lsb(pdk=None):
    return sw.v_write(pdk) / (LEVELS - 1)


def i_leak_max(pdk=None):
    """Worst-corner switch leakage [A] allowed on the store."""
    return LEAK_GUARD * lsb(pdk) * specs.design(pdk)["c_store"] / (HOLD * T_READ)


def _switch_at(pdk, corner, temp, lengths):
    """[(R_on(V_W), I_off(V_W))] of a min_w NMOS per L on one corner/temperature."""
    vw, W = sw.v_write(pdk), pdk.min_w

    def card(n, d, g, s, L):
        return pdk.fet_card.format(name=n, d=d, g=g, s=s, b="0", model=pdk.nfet,
                                   w=pdk.um(W), l=pdk.um(L), extra="")
    lines = [f"* gain_cell write switch {corner} {temp}C", pdk.lib_line(corner),
             f".temp {temp}", f"Vdd vdd 0 {pdk.vdd}", f"Vw vw 0 {vw}"]
    for k, L in enumerate(lengths):
        lines += [card(f"n{k}", "vw", "vdd", f"o{k}", L), f"Vd{k} vw o{k} {sw.DV}",
                  card(f"l{k}", f"dl{k}", "0", "0", L), f"Vl{k} dl{k} 0 {vw}"]
    lines += [".control", "op"]
    for k in range(len(lengths)):
        lines += [f"let r{k} = {sw.DV}/abs(i(Vd{k}))", f"print r{k}",
                  f"let i{k} = abs(i(Vl{k}))", f"print i{k}"]
    r = ngspice(lines + [".endc"])
    return [(r[f"r{k}"], r[f"i{k}"]) for k in range(len(lengths))]


def switch_char(pdk=None):
    """{"lengths": [...], "<corner>@<temp>": [[R_on, I_off], ...]} for a min_w write
    switch, measured once per PDK and cached."""
    pdk = pdk or get_pdk()
    lengths = [round(k * pdk.min_l, 3) for k in range(1, K_MAX + 1)]
    key = {"v_w": sw.v_write(pdk), "w": pdk.min_w, "lengths": lengths,
           "corners": list(pdk.corners), "temps": list(sw.TEMPS)}
    path = CHAR / f"{pdk.name}.json"
    if path.exists():
        got = json.loads(path.read_text())
        if got["key"] == key:
            return got
    runs = [(c, t) for c in pdk.corners for t in sw.TEMPS]
    with ThreadPoolExecutor(len(runs)) as ex:
        res = list(ex.map(lambda ct: _switch_at(pdk, *ct, lengths), runs))
    got = {"key": key, "lengths": lengths,
           "meas": {f"{c}@{t}": m for (c, t), m in zip(runs, res)}}
    CHAR.mkdir(exist_ok=True)
    path.write_text(json.dumps(got, indent=1) + "\n")
    return got


def write_size(pdk=None):
    """(W, L) um of the write switch; AnalogIOC gc_write_n 0.42/0.5."""
    pdk = pdk or get_pdk()
    ch = switch_char(pdk)
    r_max, i_max = sw.R_GUARD * sw.r_on_budget(pdk), i_leak_max(pdk)
    for k, L in enumerate(ch["lengths"]):
        r_on = max(m[k][0] for m in ch["meas"].values())
        i_off = max(m[k][1] for m in ch["meas"].values())
        # ponytail: R_on ~ 1/W and I_off ~ W from the min_w measurement; tb corners verify
        W = max(pdk.min_w, math.ceil(100 * pdk.min_w * r_on / r_max) / 100)
        if i_off * W / pdk.min_w <= i_max:
            return W, L
    raise ValueError(f"no write switch up to L={ch['lengths'][-1]} um meets both "
                     f"R_on {r_max:.3g} ohm and I_off {i_max:.3g} A")


def read_size(pdk=None):
    """(W, L) um of the read device; AnalogIOC used gc_write_n 0.42/0.5 for it too."""
    pdk = pdk or get_pdk()
    vw = sw.v_write(pdk)
    sigma_max = lsb(pdk) / 2 / 3 * VOS_SHARE ** 0.5 * 1e3     # mV
    for k in range(1, K_MAX + 1):
        L = round(k * pdk.min_l, 3)
        t = gmid.load_table("nfet", L)
        j_full = float(gmid.pchip(t["VGS"], t["ID_per_W"], vw))
        W = round(specs.I_SIDE / j_full, 2)
        if W < pdk.min_w:
            continue            # min_w would overshoot the column-current ceiling
        j_mid = float(gmid.pchip(t["VGS"], t["ID_per_W"], vw / 2))
        if max(mismatch.sigma_vgs("nfet", W, L, W * j, pdk)
               for j in (j_mid, j_full)) <= sigma_max:
            return W, L
    raise ValueError(f"read device cannot meet sigma(VGS) {sigma_max:.2f} mV "
                     f"within {K_MAX}*Lmin")


def sizes(pdk=None):
    pdk = pdk or get_pdk()
    return {"write": write_size(pdk), "read": read_size(pdk),
            "c_store": specs.design(pdk)["c_store"]}


def gain_cell_subckt(name="gain_cell", caps=True, pdk=None, sz=None):
    """Single 2T gain cell `.subckt <name> wdata wsel rd col vss` (lora_sidecar reuses
    it). caps=False drops the storage MIM (Philis deck, see __main__); `sz` overrides
    sizes() (lora_sidecar sizes its own read device)."""
    pdk = pdk or get_pdk()
    sz = sz or sizes(pdk)
    s = ps.Subcircuit(name, CELL_PORTS)
    fet(s, "w", "wdata", "wsel", "store", "vss", "nfet", *sz["write"], pdk=pdk)
    fet(s, "r", "col", "store", "rd", "vss", "nfet", *sz["read"], pdk=pdk)
    if caps:
        mim_cap(s, "s", "store", "vss", sz["c_store"], pdk=pdk)
    return s


def build(name="gain_cell_array", rows=ROWS, cols=COLS, pdk=None):
    """`.subckt <name> wdata0.. wsel0.. rd0.. col0.. vss` of `<name>_cell` instances."""
    s = ps.Subcircuit(name, ports(rows, cols))
    for r in range(rows):
        for c in range(cols):
            s.X(f"c{r}_{c}", f"{name}_cell", f"wdata{r}", f"wsel{c}", f"rd{r}",
                f"col{c}", "vss")
    return s


if __name__ == "__main__":
    # --no-caps: without the storage MIMs — Philis's feedback extraction never finishes
    # on a deck with several cap_mim devices, so the FETs are P&R'd alone and pex.py
    # re-adds the caps from the full deck
    caps = "--no-caps" not in sys.argv
    print(deck(gain_cell_subckt("gain_cell_array_cell", caps), build()), end="")

"""WTA running-max (AnalogIOC Chip 2 B3) — topology + gm/ID sizing. Prints the bare .subckt.

N-input shared-source NMOS follower-max: the follower with the highest gate holds the
common source rail mrail ~ max(vin) - VGS; a matched replica follower (gate vref, matched
tail) gives rrail = vref - VGS, so the consumer reads m_hat = mrail - rrail + vref with
VGS cancelled. vin_hold is one extra follower that re-injects the held previous max
(input domain) for the streamed running max. Chold on mrail is the settle cap.
Topology, ports and port order are AnalogIOC's (schematics/components/wta/wta.py).

Sizing (spec: analog/wta/docs/architecture.md):
  follower, tail, replica (all one matched coordinate, CHIP2_SPEC 2.3):
    gm/ID = 25 at L = 1.0 um — deep subthreshold, the translinear softmax bank's own
    coordinate (low power, and the exponential sharing that sets the n*UT*lnN range).
    Area from the random offset budget: the replica-cancelled offset is the winner vs
    replica mismatch, each side = follower + tail (VT, and in subthreshold the current
    factor too, through n*UT), so sigma_off = K_OFF*A_VT/sqrt(W*L), A_VT the pair
    coefficient (pdk_specs.a_vt). VT alone gives K_OFF = sqrt(2); tb_wta_mc measured
    sigma*sqrt(WL) = 13.5 mV*um on sky130 tt_mm at W*L = 36, 51 and 98 um^2 -> 2.56.
    Sized to 3*sigma = 4.1 mV: 18% under the 5 mV spec (a 30-sample MC sigma is only
    good to ~13%), and W stays in one instance (sky130 W bins end at 100 um; `m=`
    would not average mismatch, see NF below). The current follows: I_TAIL = W*J_D(25, L).
  vb_tail (bias the system applies): VGS(gm/ID = 25, L) — AnalogIOC 0.44 V.
  Chold: the c_hold design class (specs.design()).
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, mim_cap  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

N = 8                   # inputs per bank (CHIP2_SPEC B3/B4, 8-token bank)
PORTS = ([f"vin{i}" for i in range(N)]
         + ["vin_hold", "vref", "mrail", "rrail", "vb_tail", "vdd", "vss"])

GMID = specs.gmid_softmax()
L_DEV = specs.L_SOFTMAX
OFFSET_3SIGMA = 4.1e-3  # V, sizing target; spec 5 mV random offset (CHIP2_SPEC 2.3)
K_OFF = 2.5645          # sigma_off*sqrt(WL)/A_VT: 2.563/2.565/2.568 over 3 tb_wta_mc runs
                        # ponytail: calibration knob — per-PDK, belongs in specs._CAL
NF = 4                  # ~100 um of W as 4 x 25 um fingers (near-square). One instance, not
                        # m=2: sky130 scales mismatch by its own `mult` param, which
                        # devices.fet does not set, so m=2 would simulate half the area


def sizes(pdk=None):
    """{device: (W total, L, nf)} in um."""
    pdk = pdk or get_pdk()
    area = (3 * K_OFF * pdk.a_vt * 1e-3 / OFFSET_3SIGMA) ** 2   # um^2, a_vt mV*um
    w = round(area / L_DEV, 2)   # AnalogIOC hand value 47.4 (softmax device, not derived)
    return {"follower": (w, L_DEV, NF), "tail": (w, L_DEV, NF)}


def bias(pdk=None):
    """(vb_tail [V], I_tail [A]) at the sizing coordinate, typical corner, 27 C."""
    w = sizes(pdk)["tail"][0]
    return float(gmid.VGS(GMID, L_DEV, "nfet")), float(w * gmid.J_D(GMID, L_DEV, "nfet"))


VB_TAIL, I_TAIL = bias()   # AnalogIOC: 0.44 V typed, I_b ~0.58 uA measured


def build(pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit("wta", PORTS)
    for i in range(N):
        fet(s, f"f{i}", "vdd", f"vin{i}", "mrail", "vss", "nfet", *sz["follower"], pdk=pdk)
    fet(s, "fhold", "vdd", "vin_hold", "mrail", "vss", "nfet", *sz["follower"], pdk=pdk)
    fet(s, "tail", "mrail", "vb_tail", "vss", "vss", "nfet", *sz["tail"], pdk=pdk)
    mim_cap(s, "hold", "mrail", "vss", specs.design(pdk)["c_hold"], pdk=pdk)  # AnalogIOC 200f
    fet(s, "frep", "vdd", "vref", "rrail", "vss", "nfet", *sz["follower"], pdk=pdk)
    fet(s, "trep", "rrail", "vb_tail", "vss", "vss", "nfet", *sz["tail"], pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")

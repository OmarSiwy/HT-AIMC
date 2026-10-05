"""Score sysreference PE numbers with the shared ARCH_METRIC scorer.

    python3 scripts/score.py                 # build/ppa.json (the default config)
    python3 scripts/score.py variants        # every build/ppa.json "variants" entry + shapes

Uses scripts/compiler/metrics/arch_eval/baseline_systolic.py unchanged (same die, HBM,
rail, KV, schedule and metric as the IMC candidates); only the PE dict it reads is
swapped, so every variant is scored identically. Numbers are as labelled in ppa.json
(measured at s16, derived at array_rows x array_cols); the system model is the scorer's.
"""
import json
import sys
from pathlib import Path

BLK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BLK.parents[1] / "scripts/compiler/metrics"))
from arch_eval import baseline_systolic as B  # noqa: E402

KEYS = ("area_um2_per_pe", "fmax_GHz", "energy_per_mac_fJ", "array_rows", "array_cols",
        "leak_W_per_pe")


def score(pe, wbits=4):
    """pe: dict with KEYS (fmax_mhz accepted) -> the four metrics + peak point."""
    pe = dict(pe)
    pe.setdefault("fmax_GHz", pe.get("fmax_mhz", 0) / 1e3)
    pe = {k: float(pe[k]) for k in KEYS}
    B.ppa = lambda: (pe, dict.fromkeys(pe, "sysreference variant"))   # ponytail: swap the PE source
    s = B.evaluate(wbits)
    pk = s["peak"]
    return dict(tok_s_die=s["tok_s_die"], tops_w=s["tops_w"], tok_w=s["tok_w"],
                tok_j=s["tok_j"], vdd=pk["vdd"], clk=pk["clk_frac"], B=pk["B"],
                die_W=pk["die_power_W"], tiles=s["die"]["n_tiles"], binding=s["binding"])


def line(name, r):
    return (f"{name:28s} tok/s/die {r['tok_s_die']:8.0f}  TOPS/W {r['tops_w']:6.3f}  "
            f"tok/W {r['tok_w']:7.2f}  tok/J {r['tok_j']:7.2f}  @VDD {r['vdd']} clk x{r['clk']} "
            f"B {r['B']} die {r['die_W']:.1f} W tiles {r['tiles']}")


if __name__ == "__main__":
    ppa = json.loads((BLK / "build/ppa.json").read_text())
    if sys.argv[1:] == ["variants"]:
        for name, v in ppa.get("variants", {}).items():
            print(line(name, score(v)))
    else:
        r = score(ppa)
        print(line("default", r))
        print(json.dumps(r, indent=1, default=str))

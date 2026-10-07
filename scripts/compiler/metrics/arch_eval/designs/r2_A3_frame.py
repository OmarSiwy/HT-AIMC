"""A3 scoring frame (round 2, N5_r2.md): one command reproduces every A3 number.

    python3 designs/r2_A3_frame.py designs/r2_A3_best.json [--conditions arch|sohu|both] [--corrected]
            [--no-cw] [--bias duty] [--param key=value ...] [--json]

Frame = the joint frame (notes_native.score_design: the frame round 1 ranked in) plus the costs it never charged.
Each cost is computed by n5 (nodes/n5_array.py); model.py has no hook for them, so this file applies them
(ponytail: monkeypatch gated on _a3 in params; the integrator should move them into model.tile / n4):
  1. weight-scale bytes in HBM: stored_weights x (1 + n5.scale_bytes_frac)
  2. dequant per conversion: n5.dequant -> tile area (one 30 um2 unit per ADC) and energy (2 rail MACs)
  3. merge-cap MOM area: n5.merge_cap_um2
  4. n5 merge_load == "bridge" is one charge event: n4's +1 merge slot is removed (lands in n4 later)
Options:
  --corrected   the round-1 judge rule: ADC energy x2 and conversion time x1.25 (DECISION_r1 section 2)
  --no-cw       drop n8's +3 dB ADC class weight (the pessimistic G2 reading)
  --bias duty   n9's ml2 level-buffer bias scaled by the run clock and the word duty (critic patch; n9 today
                charges it always-on at the nominal slot)
Sohu condition: the design's nn_/kv_ params are dropped and kv_bits = 8 (A3 convention, as round 1).
All outputs projected.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1]), str(HERE.parents[2])]
import notes_native as nn  # noqa: E402
from arch_eval import design, metric, model  # noqa: E402
from arch_eval.nodes import n4_formats as n4, n5_array as n5, n6_readout as n6, n8_quality as n8, n9_circuits as n9  # noqa: E402

MODE = dict(corrected=False, no_cw=False, bias=None)

_init = nn.Ctx.__init__


def _ctx_init(self, d, knobs=None):
    _init(self, d, knobs)
    if self.p.get("_a3"):
        self.wl["stored_weights"] *= 1 + n5.scale_bytes_frac(self.p, 8)


nn.Ctx.__init__ = _ctx_init
_tile = model.tile


def _t(ctx, vdd, clk):
    t = _tile(ctx, vdd, clk)
    p = ctx.p
    if not p.get("_a3"):
        return t
    dq, mc = n5.dequant(p, t), n5.merge_cap_um2(p, t)
    e = dict(t["e_pass_J_parts"], dequant=dq["e_J"])
    a = dict(t["area_um2_parts"], dequant=dq["area_um2"], merge_caps=mc)
    return dict(t, e_pass_J_parts=e, e_pass_J=sum(e.values()), area_um2_parts=a, area_um2=sum(a.values()))


model.tile = _t
_te = n4.tile_effects


def _te2(ctx, t):
    t = _te(ctx, t)
    p = ctx.p
    if p.get("_a3") and p.get("merge_load") == "bridge" and t["fmt"].get("merge"):
        slot = t["arr"].get("slot_ns", 0.0) / t["op"]["clk_frac"]
        tw = t["t_word_ns"] - slot
        tp = max(tw, t["t_conv_ns"]) if t["rail"]["pingpong"] else tw + t["t_conv_ns"]
        t.update(t_word_ns=tw, t_pass_s=tp * 1e-9)
    return t


n4.tile_effects = _te2
_adc = n6.adc


def _adc2(p, vdd, v):
    a = _adc(p, vdd, v)
    if MODE["corrected"]:
        a = dict(a, e_conv_fJ=a["e_conv_fJ"] * 2, t_conv_ns=a["t_conv_ns"] * 1.25)
    return a


n6.adc = _adc2
_plumb = n9.plumb


def _plumb2(p, t):
    t = _plumb(p, t)
    sd = t.get("n9", {}).get("ml2_pq_mW", 0) * 1e-3
    if sd and MODE["bias"] == "duty":
        f = t["op"]["clk_frac"] * min(1.0, t["t_word_ns"] / (t["t_pass_s"] * 1e9))
        t = dict(t, leak_W=t["leak_W"] - sd * (1 - f))
    return t


n9.plumb = _plumb2
CW_ADC = n8.CLASS_DB["adc"]


def score(nodes, params, cond="arch", **mode):
    MODE.update(dict(corrected=False, no_cw=False, bias=None), **mode)
    n8.CLASS_DB["adc"] = 0.0 if MODE["no_cw"] else CW_ADC
    q = dict(params, _a3=True)
    if cond == "sohu":
        q = {k: v for k, v in q.items() if not k.startswith(("nn_", "kv_"))}
        q["kv_bits"] = 8
    try:
        s = nn.score_design(design.make(nodes, q), metric.knobs_for(cond))
    finally:
        n8.CLASS_DB["adc"] = CW_ADC
    t, pk = s.get("tile") or {}, s.get("peak") or {}
    return dict(tok_s=round(s["tok_s_die"]), tops_w=round(s["tops_w"], 2), tok_w=round(s["tok_w"], 1),
                tok_j=round(s["tok_j"], 1), margin=round(s["margin_db"], 2), area=round(t.get("area_um2", 0)),
                t_pass_ns=round(t.get("t_pass_s", 0) * 1e9, 3), snr=round(t.get("snr_db", 0), 2),
                vdd=pk.get("vdd"), B=pk.get("B"), bind=s.get("binding"), errors=s["errors"][:2],
                aparts={k: round(v) for k, v in (t.get("area_um2_parts") or {}).items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--conditions", default="both", choices=["arch", "sohu", "both"])
    ap.add_argument("--corrected", action="store_true")
    ap.add_argument("--no-cw", action="store_true")
    ap.add_argument("--bias", choices=["duty"])
    ap.add_argument("--param", action="append", default=[], help="key=value (JSON value) override")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = json.load(open(a.design))
    prm = dict(d["params"], **{kv.split("=", 1)[0]: json.loads(kv.split("=", 1)[1]) for kv in a.param})
    out = {c: score(d["nodes"], prm, c, corrected=a.corrected, no_cw=a.no_cw, bias=a.bias)
           for c in (("arch", "sohu") if a.conditions == "both" else (a.conditions,))}
    print(json.dumps(out, indent=1, default=str) if a.json else
          "\n".join(f"{d.get('name', a.design)} [{c}] tok/s {r['tok_s']} TOPS/W {r['tops_w']} tok/W {r['tok_w']} "
                    f"tok/J {r['tok_j']} margin {r['margin']:+.2f} dB area {r['area']} um2 t_pass {r['t_pass_ns']} ns"
                    for c, r in out.items()))


if __name__ == "__main__":
    main()

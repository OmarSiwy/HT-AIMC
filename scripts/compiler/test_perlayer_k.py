"""Falsifier for the heterogeneous per-tensor K schedule (perlayer_k.py).

Asserts the three properties the schedule must have:
  1. every tensor's K respects its SNR budget: cascade_snr_db(K) >= SNRt;
  2. FFN gets DEEPER K than attention (that is the whole point);
  3. aggregate tok/s/die sits between the uniform-K=4 floor and the
     uniform-K=14 ceiling at every PDK/scale.
Plus: what binds (attention random term, FFN gain term).

Run: PYTHONPATH=analog/schematics python3 scripts/compiler/test_perlayer_k.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "metrics"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                "analog", "schematics"))
import specs                       # noqa: E402
import perlayer_k as plk           # noqa: E402


def test():
    mats = json.load(open(plk.MANIFEST))["matrices"]
    total = sum(mats[n]["passes_per_token"] for n in mats)
    assert total == 10944, total          # counted A5 tiling anchor
    sched, rows = plk.project(mats, total)

    # (1) every tensor's K respects its SNR budget
    for n, K in sched.items():
        snr = specs.cascade_snr_db(
            K, snr_s_db=plk.SNR_S_DB[plk.tensor_class(n)])
        assert snr >= plk.SNR_T_DB, (n, K, snr)
        # and it is the FLOOR: K+1 would violate the budget
        snr_up = specs.cascade_snr_db(
            K + 1, snr_s_db=plk.SNR_S_DB[plk.tensor_class(n)])
        assert snr_up < plk.SNR_T_DB, (n, K + 1, snr_up)
    print("(1) every K respects cascade_snr_db(K) >= SNRt and is the floor")

    # (2) FFN deeper than attention
    attn = [sched[n] for n in sched if plk.tensor_class(n) == "attn"]
    ffn = [sched[n] for n in sched if plk.tensor_class(n) == "ffn"]
    assert min(ffn) > max(attn), (attn, ffn)
    print(f"(2) FFN K {sorted(set(ffn))} > attention K {sorted(set(attn))}")

    # (3) aggregate bracketed by uniform K=4 and K=14
    for r in rows:
        assert r["u4"] <= r["het"] <= r["u14"], r
        assert r["het_vs_u4"] > 1.0, r     # heterogeneous beats uniform-4
    print("(3) het tok/s in [uniform-K4, uniform-K14] at every PDK/scale, "
          "and > uniform-K4")

    # what binds (documented honesty): attn random, ffn gain
    binds = {c: ("gain (1+eg)^K"
                 if specs.math.log(1.02) / specs.EG_SERVO
                 < 10.0 ** ((s - plk.SNR_T_DB) / 10.0)
                 else "random sqrt(K)")
             for c, s in plk.SNR_S_DB.items()}
    assert binds["attn"] == "random sqrt(K)", binds
    assert binds["ffn"] == "gain (1+eg)^K", binds
    n4 = next(r for r in rows if r["pdk"].startswith("tsmc_n4")
              and r["scale"] == "7B")
    print(f"binds: attn={binds['attn']}, ffn={binds['ffn']} "
          f"(FFN K capped by gain term, not throughput)")
    print(f"N4 7B: het {n4['het']:,.0f} tok/s/die = {n4['het_vs_sohu']:.2f}x "
          f"Sohu, {n4['het_vs_u4']:.2f}x uniform-K4 (avg K {n4['avg_k']:.2f})")
    print("PASS")


if __name__ == "__main__":
    test()

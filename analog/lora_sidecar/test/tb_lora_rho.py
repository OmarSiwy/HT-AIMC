"""lora_sidecar: measure rho and the level table; record them for specs.lora_cal().

rho is the code units one unit of B_eff * A_eff * x adds to a column (golden
tile_mvm(lora=(A, B, rho))). Spec rows (analog/lora_sidecar/docs/architecture.md):
  levels   level table I_m / I_7 for m = 0..7 (sign-magnitude codes 8 + m on the write
           DAC), strictly monotone; level 0 < 1 % (an unused cell of a pair is off)
  rho      least-squares over the two reference passes; agrees with the physical
           rho_phys = dV_ax I_B7 / (49 sum(m) slope q_unit) within 5 % (ratio to
           specs.lora_rho_design() reported)
  c0       window pedestal (colb switch charge per B window) |c0| < TOL_ABS
  linear   Delta mac vs A.x: 1..4 reference rows at x = 15 -> 1:2:3:4 within TOL_ABS
  mirror   negative-path error |km - 1| * level <= 2 % of full scale at every level
On DUT=sch at the typical corner and 27 C it writes analog/docs/lora_cal/<pdk>.json
(specs.lora_cal()); other corners print their own numbers (per-chip calibration).
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lora_bench as LB  # noqa: E402
from bench import Report, dut_kind  # noqa: E402


def main():
    r = Report("lora_sidecar: rho + level table")
    run = LB.Run()
    LB.cal_program(run)
    pp, pn = LB.cal_passes(run)
    lin = []
    for k in range(1, LB.CAL_ROWS + 1):
        x = np.zeros(LB.N, int)
        x[:k] = LB.CAL_X
        lin.append(run.lora_pass(x, "lo", f"{k} rows"))
    run.simulate()

    cal = LB.calibrate(run, pp, pn)
    lv = cal["levels"]
    print(f"  levels: {' '.join(f'{v:.4f}' for v in lv)}  (I_7 = {cal['i_b7'] * 1e9:.1f} nA,"
          f" design {LB.specs.lora_i_cell() * 1e9:.1f} nA)")
    print(f"  mirror gain: {' '.join(f'{k:.4f}' for k in cal['km'])}")
    r.check("levels strictly monotone", np.all(np.diff(lv) > 0))
    r.check("level 0 off (< 1 % of level 7)", lv[0] < 0.01, f"{lv[0] * 100:.3f} %")
    km = np.array(cal["km"])
    mir = np.abs(km - 1) * np.array(lv[1:])
    r.check("mirror path error <= 2 % of full scale at every level", np.all(mir <= 0.02),
            f"gain {km.min():.4f} .. {km.max():.4f}, worst {mir.max() * 100:.2f} % FS")
    r.check("window pedestal |c0| < TOL_ABS", abs(cal["c0"]) < LB.TOL_ABS,
            f"c0 {cal['c0']:+.3f} code (switch charge per B window, every column)")
    rel = cal["rho"] / cal["rho_phys"] - 1
    r.check("rho fit vs physical within 5 %", abs(rel) <= 0.05,
            f"rho {cal['rho']:.5f}, phys {cal['rho_phys']:.5f} ({rel * 100:+.2f} %)")
    print(f"  rho / specs.lora_rho_design() = {cal['rho'] / LB.specs.lora_rho_design():.3f}"
          f" (design assumes the written store reaches V_W: I_7 {cal['i_b7'] * 1e9:.0f} nA vs"
          f" {LB.specs.lora_i_cell() * 1e9:.0f} nA)")
    b = np.array(LB.CAL_B)
    d = np.array([run.dmac(p, cal) for p in lin])            # [k rows, column]
    ref = np.outer(np.arange(1, LB.CAL_ROWS + 1), d[0])
    err = np.max(np.abs(d - ref)[:, np.abs(b) >= 4])
    r.check("Delta mac linear in A.x (1..4 rows)", err <= LB.TOL_ABS,
            f"max deviation from k x one-row {err:.2f} code")
    print(f"  ramp slope {cal['slope'] * 1e-6:.3f} V/us (I_ramp/C_int design "
          f"{LB.specs.lora_i_ramp() / LB.specs.lora_c_int() * 1e-6:.3f}); "
          f"A swing {cal['dv_ax'] * 1e3:.0f} mV")

    nominal = (dut_kind() == "sch" and os.environ.get("CORNER", LB.PDK.typical) ==
               LB.PDK.typical and float(os.environ.get("SIM_TEMP", 27)) == 27.0)
    if nominal and r.ok:
        out = Path(LB.specs.LORA_CAL_DIR) / f"{LB.PDK.name}.json"
        out.parent.mkdir(exist_ok=True)
        keep = ("rho", "c0", "levels", "km", "rho_phys", "i_b7", "slope", "dv_ax")
        out.write_text(json.dumps({"pdk": LB.PDK.name, "corner": LB.PDK.typical,
                                   "temp": 27, **{k: cal[k] for k in keep}}, indent=1) + "\n")
        print(f"  wrote {out}")
    r.done()


if __name__ == "__main__":
    main()

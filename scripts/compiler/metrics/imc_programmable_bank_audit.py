"""Check charge-integration convergence against the bank's numerical budget."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def compare(first, second, output):
    assert not output.exists(), f"Preserve prior evidence: {output}"
    a,b=(json.loads(p.read_text()) for p in (first,second))
    for key in ("width_um","corner","temp_C","unit_fF","settle_ns","slot_ns","stop_ns"):
        assert a[key]==b[key], f"Different physical fixture: {key}"
    assert b["step_ps"]<a["step_ps"]
    assert a.get("column_bias_V",.9)==b.get("column_bias_V",.9), "Different column bias"
    assert a.get("amplitudes_V",[.45,-.45,0,.225,-.225])==b.get("amplitudes_V",[.45,-.45,0,.225,-.225]), "Different row stimuli"
    assert a.get("coupon_projection")==b.get("coupon_projection"), "Different capacitor projection"
    assert a.get("width_p_um",a["width_um"])==b.get("width_p_um",b["width_um"]), "Different PMOS sizing"
    assert a.get("bits",4)==b.get("bits",4), "Different bank size"
    assert (a.get("sign"),a.get("sign_mux_scale"))==(b.get("sign"),b.get("sign_mux_scale")), "Different sign mux"
    assert a.get("sign_routing","shared" if a.get("sign") is not None else None)==b.get("sign_routing","shared" if b.get("sign") is not None else None), "Different sign routing"
    differences=[]
    for x,y in zip(a["rows"],b["rows"],strict=True):
        assert (x["mode"],x["code"])==(y["mode"],y["code"])
        norm=max(x["code"],1)*a["unit_fF"]*.45
        differences.append(float(np.max(abs(np.array(x["charge_fC"])-y["charge_fC"]))/norm))
    limit=.1*a["gates"]["max_charge_error_fraction_per_weight_full_scale"]
    gates=dict(ideal_oracles=all(d["quadrature_protocol_v2"]["oracle_pass"] for d in (a,b)),
        timestep_difference=max(differences)<=limit,
        physical_charge_gate=all(all(d["pass_by_mode"].values()) for d in (a,b)))
    result=dict(inputs=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (first,second)],
        gates=gates,pass_all=all(gates.values()),max_timestep_difference_fraction_FS=max(differences),
        difference_limit_fraction_FS=limit,
        scope="Two-step numerical agreement for the specified clamped programmable bank, including sign routing when present in both fixtures; no array, SRAM, sampled noise or broader PVT qualification")
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(("PASS" if result["pass_all"] else "FAIL")+" BANK NUMERICAL CONTROL "+json.dumps(gates))
    assert result["pass_all"]


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first",type=Path)
    parser.add_argument("second",type=Path)
    parser.add_argument("output",type=Path)
    compare(**vars(parser.parse_args()))

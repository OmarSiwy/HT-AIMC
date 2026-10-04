"""Audit retained dense traces in voltage/charge units without resimulation.

The physical residual allocation was frozen before any dense result: RMS
one eighth and maximum one half of a 0.1171875fC ADC quantum. This is a
separate provisional screen, not a replacement for the archived raw-MAC gate.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/"build/campaign/dense_core"


def audit(name):
    directory=OUT/name
    source=directory/"result.json"
    metadata=json.loads(source.read_text())
    result=metadata["result"]
    replay=result["accumulator_replay"]
    error=np.array(replay["recovered_MAC"])-np.array(replay["exact_MAC"])
    voltage=error*np.array(replay["full_gain_uV_per_MAC"])
    native_ff=result["load_ff"]+result["cu_ff"]*np.sum(abs(np.array(result["weights"])),axis=1)
    charge=voltage*native_ff*1e-6
    quantum=3.75*.5/16
    rms=np.sqrt(np.mean(charge**2,axis=0))/quantum
    maximum=np.max(abs(charge),axis=0)/quantum
    trace=np.loadtxt(directory/"trace.csv")
    assert trace[-1,0]>=len(result["inputs"])*result["cycle_ns"]*1e-9-1e-12
    frames=np.arange(54)
    sample=3*result["evaluate_ns"]+1.6
    before=(frames*result["cycle_ns"]+sample+.1)*1e-9
    closed=(frames*result["cycle_ns"]+sample+.4+result["share_hold_ns"]-.1)*1e-9
    ratios=[]
    for col in range(8):
        array=np.interp(before,trace[:,0],trace[:,1+col])-.9
        old=np.interp(before,trace[:,0],trace[:,9+col])-.9
        new=np.interp(closed,trace[:,0],trace[:,9+col])-.9
        matrix=np.column_stack([old-array,np.ones(len(old))])
        ratio,offset=np.linalg.lstsq(matrix,new-array,rcond=None)[0]
        residual=new-array-matrix@np.array([ratio,offset])
        ratios.append(dict(column=col,holder_fraction=float(ratio),offset_uV=float(offset*1e6),
            residual_rms_uV=float(np.sqrt(np.mean(residual**2))*1e6),
            approximate_trim_delta_fF=float(-4*native_ff[col]*(ratio-.5))))
    report=dict(source=str(source.relative_to(ROOT)),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        legacy_raw_MAC_gate=result["accumulator_transfer_pass"],
        native_capacitance_fF=native_ff.tolist(),held_error_uV=voltage.tolist(),
        rms_held_error_uV=float(np.sqrt(np.mean(voltage**2))),max_held_error_uV=float(np.max(abs(voltage))),
        equivalent_charge_error_fC=charge.tolist(),delta_Q_fC=quantum,
        per_column_rms_ADC_LSB=rms.tolist(),per_column_max_ADC_LSB=maximum.tolist(),
        coherent_mean_ADC_LSB=(np.mean(charge,axis=0)/quantum).tolist(),
        limits=dict(rms_ADC_LSB=.125,max_ADC_LSB=.5),
        provisional_physical_residual_pass=bool(np.all(rms<=.125) and np.all(maximum<=.5)),
        rejected_incomplete_cycle_share_fit=ratios,calibration_frames=list(range(54)),
        scope="Nominal native capacitance converts voltage residual to equivalent charge; parasitics, calibration drift, random noise, ADC transfer and system quality remain independent gates")
    path=directory/"physical_audit.json"
    assert not path.exists(),f"Preserve previous audit: {path}"
    path.write_text(json.dumps(report,indent=2)+"\n")
    print(("PASS" if report["provisional_physical_residual_pass"] else "FAIL")+
          " PROVISIONAL PHYSICAL RESIDUAL "+name+" "+json.dumps(report),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    audit(parser.parse_args().name)

"""Audit saved gm/ID sizing experiments and export their measured tradeoffs.

No SPICE is run and no incomplete transient is promoted to an accuracy result.
The Pareto set is limited to the saved TT development screen at equal range.
"""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/"build/research/imc_log_sizing"


def main():
    rows=[]
    for path in sorted(OUT.glob("*.json")):
        record=json.loads(path.read_text())
        if "design" not in record or "result" not in record:
            continue
        r,s=record["result"],record["design"]
        wd=Path(r["artifacts"])
        deck=wd/(wd.name+".cir")
        assert hashlib.sha256(deck.read_bytes()).hexdigest()==r["netlist_sha256"],path
        assert hashlib.sha256((wd/"generator_snapshot.py").read_bytes()).hexdigest()==r["source_sha256"],path
        xy=np.array(r["operands"])
        output=np.array(r["output_current_A"])
        errors=output[1:]/output[0]/xy[1:].prod(1)-1
        maximum=float(max(abs(errors)))
        rms=float(np.sqrt(np.mean(errors**2)))
        assert abs(maximum-r["max_product_relative_error"])<1e-12
        assert abs(rms-r["rms_product_relative_error"])<1e-12
        assert bool(maximum<.01)==r["product_1percent_pass"]
        assert bool(r["read_window_max_relative_error"]<.01)==r["read_window_1percent_pass"]
        assert abs(np.mean(r["delivered_per_word_J"][1:])*1e12-r["delivered_mean_evaluation_pJ"])<1e-9
        rows.append(dict(record=path.name,corner=r["corner"],temperature_C=r["temp_C"],
            seed=r["seed"],grid=r.get("added_grid_per_axis",0),step_ns=r["step_ns"],
            table_gm_ID=s["table_gm_ID"],L_um=r["nmos_L_um"],W_um=r["nmos_W_um"],
            output_W_um=r.get("output_W_um",r["nmos_W_um"]),cap_fF=r["cap_fF"],
            reference_ratio=r.get("reference_current_ratio",1),
            acquire_ns=r["acquire_us"]*1000,evaluate_ns=r["evaluate_us"]*1000,
            word_ns=r["word_us"]*1000,max_error_percent=100*maximum,
            rms_error_percent=100*rms,window_error_percent=100*r["read_window_max_relative_error"],
            delivered_pJ=r["delivered_mean_evaluation_pJ"],
            MOS_gate_area_proxy_um2=s["MOS_gate_area_proxy_um2"],
            pass_gate=r["read_window_1percent_pass"],source_sha256=r["source_sha256"],
            netlist_sha256=r["netlist_sha256"]))
    assert rows,"No completed sizing experiments"
    population=[r for r in rows if r["corner"]=="tt" and r["seed"]==97402 and not r["grid"]]
    metrics=("window_error_percent","word_ns","delivered_pJ","cap_fF","MOS_gate_area_proxy_um2")
    frontier=[r["record"] for r in population if not any(
        all(q[m]<=r[m] for m in metrics) and any(q[m]<r[m] for m in metrics)
        for q in population)]
    incomplete=[]
    for wd in sorted((ROOT/"build/sim").glob("imc_log_charge_*")):
        if not wd.is_dir() or (wd.parent/(wd.name+".json")).exists():
            continue
        logfile=wd/(wd.name+".log")
        if not logfile.exists():
            continue
        log=logfile.read_text(errors="replace")
        reason=("NUMERICAL_NONCONVERGENCE" if "Timestep too small" in log else
                "UNSUPPORTED_MODEL_GEOMETRY" if "valid modelname" in log else "NO_COMPLETED_RESULT")
        incomplete.append(dict(artifact=str(wd.relative_to(ROOT)),status=reason))
    summary=dict(scope="Saved deterministic positive scalar product screens; not a chip or yield result",
        records=rows,completed=len(rows),passing=sum(r["pass_gate"] for r in rows),
        incomplete_or_rejected=incomplete,
        pareto_scope="TT27 seed97402 development, same centered factor-two operand interval; finite tested population only",
        pareto_metrics=metrics,pareto_frontier=frontier)
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    with (OUT/"sweep.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    print(f"PASS: {len(rows)} completed result/provenance audits; {summary['passing']} pass1% window; {len(incomplete)} incomplete/rejected decks retained")


if __name__=="__main__":
    main()

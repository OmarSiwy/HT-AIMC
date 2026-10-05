"""GPurify macro spec for analogioc, generated from netlist/analogioc.ports + INTERFACE.md.

    python3 liberty.py [out.json]        (default: ../output/lib/liberty.json)

The spec is generated, not committed: it is ~0.8 MB (every arc case drives all 415 inputs,
which GPurify requires) and carries this machine's absolute model path.

GPurify writes each corner's `models` line verbatim into an ngspice deck, and neither
expands environment variables, so the model path is resolved here from $PDK_ROOT/$PDK
(default ~/.ciel/sky130A). `make -C analog/analogioc/build/lib lib` re-runs this first.
$GPURIFY_SIM picks the simulator binary GPurify drives in pipe mode (default ngspice).

Pins: one per .ports bit, in .subckt order, Verilog bit names (`x_mag[0]`, as the LEF from
macro_views.py). Roles: digital in -> input, digital out -> output, analog -> analog
(inout, biased at its INTERFACE.md §2 operating point, D = 1), supplies -> power/ground.
There is no clock pin: the macro is self-timed (INTERFACE.md §4).

Arcs: the completion edges of the three 4-phase handshakes, as combinational arcs (a
self-timed go -> done; GPurify keeps the slowest case and min/ the fastest):
  integ_req -> integ_ack      rise/rise, fall/fall           (§6.2 I1..I8)
  cmp_req[j] -> cmp_ack[j]    rise/rise (dac 0 and 15), fall/fall  (§6.4)
  cb_ack[j]  -> cb_req[j]     rise/fall                      (§6.3 C3..C4)
The bundled data (col_sign, cb_cross, cmp_result) gets no arc of its own: by contract it
settles T_BUNDLE >= 2 ns before its qualifying edge above, and the rail samples both
through 2FF synchronizers. Not run yet: the preparation sequences are written from the
contract and untested.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORTS = HERE.parent / "netlist" / "analogioc.ports"
COLS = 17

# Analog pin operating points (INTERFACE.md §2, D = 1, u_cal 1.337 mV, trim 0.8)
VCM = 0.9
THR = 15.5 * 1.337e-3
SAR = 16 * 1.337e-3 * 0.8
BIAS = {
    "vcm": VCM,
    "vrn_thrp": VCM, "vrp_thrp": VCM + THR,
    "vrn_thrn": VCM - THR, "vrp_thrn": VCM,
    "vrn_sarp": VCM, "vrp_sarp": VCM + SAR,
    "vrn_sarn": VCM - SAR, "vrp_sarn": VCM,
    "vb_nc": 1.25, "vb_pc": 0.29, "vb_tail": 0.665, "vb_ramp": 0.656,
}
# name, temperature, supply V (every rail; vss 0), sky130 model section
CORNERS = [("tt_025C_1v80", 25, 1.8, "tt"), ("ss_100C_1v60", 100, 1.6, "ss"),
           ("ff_n40C_1v95", -40, 1.95, "ff")]
# Run time: every point is a transient of the whole extracted macro, so the tables are
# 2 x 2 (sky130_fd_sc_hd's are 7 x 7). vector_ns covers the slowest preparation step,
# an LO integrate handshake (~300 ns on the sim grid, §6.2); settle_ns its response.
CHARACTERIZATION = {"slews_ns": [0.1, 1.0], "loads_pf": [0.005, 0.05],
                    "vector_ns": 500, "settle_ns": 500}


def ports():
    rows = []
    for line in PORTS.read_text().splitlines():
        tok = line.split("#", 1)[0].split()
        if tok:
            rows.append(tok[:4])
    return rows


def spec():
    rows = ports()
    pins, inputs = [], []
    for name, d, kind, domain in rows:
        if kind == "supply":
            pins.append({"name": name, "role": "ground" if name == "vss" else "power"})
            continue
        pin = {"name": name, "power": domain, "ground": "vss"}
        if kind == "analog":
            pin.update(role="analog", direction="inout", bias=round(BIAS[name], 6))
        else:
            pin["role"] = "input" if d == "in" else "output"
            if d == "in":
                inputs.append(name)
        pins.append(pin)

    # Idle, reset released: every input 0 but ota_en (OTAs awake) and pkt_d = 1 (D = 1).
    base = {n: "0" for n in inputs}
    base.update({n: "1" for n in inputs if n.startswith("ota_en[")})
    base["pkt_d[0]"] = "1"
    reset = dict(base, seq_rst_n="0")
    run = {"seq_rst_n": "1"}
    integrated = [reset, run, {"integ_req": "1"}, {"integ_req": "0"}]  # I1..I8 done

    def case(vectors, edge, output):
        return {"vectors": vectors, "edge": edge, "output": output}

    arcs = [
        {"from": "integ_req", "to": "integ_ack", "kind": "combinational",
         "cases": [case([reset, run], "rise", "rise")]},
        {"from": "integ_req", "to": "integ_ack", "kind": "combinational",
         "cases": [case([reset, run, {"integ_req": "1"}], "fall", "fall")]},
    ]
    for j in range(COLS):
        req, ack = f"cmp_req[{j}]", f"cmp_ack[{j}]"
        code = lambda v: {f"dac_code[{4 * j + b}]": v for b in range(4)}
        arcs += [
            {"from": req, "to": ack, "kind": "combinational", "cases": [
                case([dict(reset, **code(v)), *integrated[1:]], "rise", "rise") for v in ("0", "1")]},
            {"from": req, "to": ack, "kind": "combinational", "cases": [
                case([*integrated, {req: "1"}], "fall", "fall")]},
            {"from": f"cb_ack[{j}]", "to": f"cb_req[{j}]", "kind": "combinational", "cases": [
                case([*integrated, {f"coarse_en[{j}]": "1"}], "rise", "fall")]},
        ]

    pdk = Path(os.environ.get("PDK_ROOT", Path.home() / ".ciel")) / os.environ.get("PDK", "sky130A")
    lib = pdk / "libs.tech" / "ngspice" / "sky130.lib.spice"
    corners = [{"name": n, "temperature": t,
                "supplies": {p["name"]: (0 if p["role"] == "ground" else v)
                             for p in pins if p["role"] in ("power", "ground")},
                "models": [f'.lib "{lib}" {s}'], "mc_models": [f'.lib "{lib}" {s}_mm']}
               for n, t, v, s in CORNERS]
    return {
        "cell": "analogioc",
        "substrate": "vss",
        "pins": pins,
        "arcs": arcs,
        "corners": corners,
        "leakage_states": [[dict(reset, **{n: "0" for n in inputs if n.startswith("ota_en[")}), run]],
        "characterization": CHARACTERIZATION,
        "simulator": {"binary": os.environ.get("GPURIFY_SIM", "ngspice")},
    }


def check(s):
    """What GPurify's validate() would refuse, plus the contract's counts."""
    pins = s["pins"]
    roles = [p["role"] for p in pins]
    assert len(pins) == 519, len(pins)
    assert (roles.count("input"), roles.count("output"), roles.count("analog")) == (415, 86, 13)
    assert all(re.fullmatch(r"\w+(\[\d+\])?", p["name"]) for p in pins)
    inputs = {p["name"] for p in pins if p["role"] == "input"}
    names = {p["name"] for p in pins}
    for a in s["arcs"]:
        assert a["from"] in inputs and a["to"] in names, a["from"]
        for c in a["cases"]:
            assert set(c["vectors"][0]) >= inputs, f"{a['from']}: first vector leaves inputs undriven"
            assert all(set(v) <= inputs for v in c["vectors"])


if __name__ == "__main__":
    s = spec()
    check(s)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "output" / "lib" / "liberty.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(s, indent=1) + "\n")
    print(f"liberty.py: {out}: {len(s['pins'])} pins, {len(s['arcs'])} arcs, "
          f"{len(s['corners'])} corners, models {s['corners'][0]['models'][0]}")

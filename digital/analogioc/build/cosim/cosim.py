"""Mixed-signal co-simulation: digital RTL inside ESPice as a VerA `.v` device.

    python3 cosim.py smoke                    toy macro, seconds: proves the A/D bridge
    python3 cosim.py gen   [PASS ...]         analogioc_top RTL + analogioc SPICE deck (A9/A12)
    python3 cosim.py check [PASS ...]         decode out/cosim.csv, gate codes with +-CODE_TOL
    python3 cosim.py elab                     VerA elaboration check of the generated device

Mechanism (INTERFACE.md §10 "co-sim"): ESPice loads a Verilog-1364 design with `.hdl`
and runs it as one device (VerA's event engine). Every input pin is an A2D bridge
(threshold `vth`), every output pin a D2A Thevenin driver (`rout`, `trise`/`tfall`
ramps). So the bridge is the device card plus the wiring generated here:

  cosim_dut   device top: one scalar pin per macro bit (.ports order), plus the
              observation pins; instantiates the digital top and the stimulus
  <macro>     a shell module with the macro's Verilog ports, standing in for the
              behavioural model: its outputs read the device pins upward
              (cosim_dut.p_<bit>), its inputs are read downward by cosim_dut

A device keeps no transcript (its $display is dropped, a rejected time step would
replay it), so results leave through pins: a byte FIFO serialised on obs_d[7:0],
one byte per obs_v toggle, decoded from the rawfile by `check`.

Expected values: analog/analogioc/test/pass_vectors.py (golden, bit-true); the gate
is |code - expected| <= CODE_TOL (INTERFACE.md §11) instead of the beh tb's exact match.
"""
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "analog/analogioc/test"))
sys.path.insert(0, str(ROOT / "analog/docs"))

CODE_TOL = 8            # LSB, INTERFACE.md §11
VDD = 1.8
T_CLK = 20              # ns, LibreLane CLOCK_PERIOD = T_CLK_MAX
# D2A/A2D card. ponytail: one driver for every pin; sky130_fd_sc_hd buf_2-class
# edges (~150 ps into a few fF) and a 200 ohm Thevenin. Per-pin drive strength
# when the macro's input load is known (PEX).
CARD = dict(vdd=VDD, vth=VDD / 2, vhys=0, rout=200, trise="150p", tfall="150p")
OBS = ["obs_v"] + [f"obs_d{k}" for k in range(7, -1, -1)] + ["done"]   # device output order
COMPILER_OUT = Path(os.environ.get("COMPILER_OUT", ROOT / "scripts/compiler/out"))
ESPICE = os.environ.get("ESPICE", "espice")
VERA = os.environ.get("VERA", "vera")


# --------------------------------------------------------------------------- ports
def read_ports(path):
    """[(bit, direction, kind)] in .subckt order; bit is 'name' or 'name[i]'."""
    rows = [l.split() for l in Path(path).read_text().splitlines() if l.strip() and not l.startswith("#")]
    return [(r[0], r[1], r[2]) for r in rows]


def net(bit):
    """SPICE/Verilog-safe scalar name of a port bit: x_mag[3] -> x_mag_3."""
    return re.sub(r"\[(\d+)\]", r"_\1", bit)


def vectors(ports, kind="digital"):
    """{name: (direction, [bits LSB first])} of the macro's Verilog ports, port order."""
    out = {}
    for bit, d, k in ports:
        if k == kind:
            out.setdefault(bit.split("[")[0], (d, []))[1].append(bit)
    return out


# --------------------------------------------------------------------------- verilog
def obs_verilog():
    """Byte FIFO + serialiser (posedge: data, negedge: obs_v toggles) and `done`."""
    return """
    // ---- observation channel: results leave through pins (no device transcript)
    reg [7:0] obs_mem [0:4095];
    integer   obs_wp, obs_rp;
    reg [7:0] obs_d;
    reg       obs_v, obs_tgl, done, fin;
    initial begin obs_wp = 0; obs_rp = 0; obs_d = 0; obs_v = 0; obs_tgl = 0; done = 0; fin = 0; end
    always @(posedge clk) begin
        obs_tgl <= 1'b0;
        if (obs_rp != obs_wp) begin obs_d <= obs_mem[obs_rp]; obs_rp <= obs_rp + 1; obs_tgl <= 1'b1; end
        else if (fin) done <= 1'b1;
    end
    always @(negedge clk) if (obs_tgl) obs_v <= ~obs_v;
    assign p_obs_v = obs_v;
    assign p_done  = done;
"""


def device_verilog(ports, macro, inst, body):
    """cosim_dut (device top) + the `macro` shell; `body` instantiates the digital
    top, whose macro instance is at hierarchical path `inst`."""
    dig = [(b, d) for b, d, k in ports if k == "digital"]
    pins = [f"    output wire p_{net(b)}" if d == "in" else f"    input  wire p_{net(b)}" for b, d in dig]
    pins += [f"    output wire p_{o}" for o in OBS]
    obs_bus = "\n".join(f"    assign p_obs_d{k} = obs_d[{k}];" for k in range(8))
    down = "\n".join(f"    assign p_{net(b)} = {inst}.{b};" for b, d in dig if d == "in")
    vec = vectors(ports)
    shell_ports, shell_body = [], []
    for name, (d, bits) in vec.items():
        w = f"[{len(bits) - 1}:0] " if bits[0].endswith("]") else ""
        shell_ports.append(f"    {'input ' if d == 'in' else 'output'} wire {w}{name}")
        if d == "out":
            cat = ", ".join(f"cosim_dut.p_{net(b)}" for b in reversed(bits))
            shell_body.append(f"    assign {name} = {{{cat}}};" if w else f"    assign {name} = cosim_dut.p_{net(bits[0])};")
    for name in vectors(ports, "analog"):
        shell_ports.append(f"    inout  wire {name}")
    # push(b) appends a byte to the FIFO. Inlined, not a task: VerA 1.0.0 panics
    # (digital.compile.infer) on a task enable once abft_check/bacc_accum are in
    # the design (REQUIRED_TOOLING.md §4).
    body = re.sub(r"push\((.*?)\);", r"begin obs_mem[obs_wp] = \1; obs_wp = obs_wp + 1; end", body)
    return f"""// GENERATED by digital/analogioc/build/cosim/cosim.py -- do not edit.
`timescale 1ns/1ps
module cosim_dut (
{(","+chr(10)).join(pins)}
);
    reg clk, rst_n;
    initial begin clk = 0; rst_n = 0; #{3 * T_CLK} rst_n = 1; end
    always #{T_CLK // 2} clk = ~clk;
{obs_verilog()}{obs_bus}
    // ---- macro inputs: read down from the shell's ports
{down}
{body}
endmodule

// Shell of the analog macro: same Verilog ports as {macro}_beh.v. Its outputs are
// the device's A2D pins; its inputs are read by cosim_dut. The circuit is in SPICE.
module {macro} (
{(","+chr(10)).join(shell_ports)}
);
{chr(10).join(shell_body)}
endmodule
"""


def pass_vectors(names):
    import pass_vectors as PV
    assert (COMPILER_OUT / "passes").is_dir(), f"no {COMPILER_OUT}/passes: run python3 scripts/compiler/compile.py"
    dig = json.loads((COMPILER_OUT / "digital_config.json").read_text())
    dirs = sorted((COMPILER_OUT / "passes").glob("pass_*"))
    pick = [next(p for p in dirs if p.name.startswith(f"pass_{n}")) for n in names]
    return [PV.pass_vectors(p, dig) for p in pick]


def pack(vals, width):
    return sum((int(v) & ((1 << width) - 1)) << (width * k) for k, v in enumerate(vals))


def real_body(vecs):
    """analogioc_top + the cocotb Bench (test_analogioc.py) in Verilog: weight sets
    streamed on wt_* ahead of the passes, each pass's cfg applied while idle, res_ready
    = 1. Every code_valid pushes [1, code_hi x17, code_lo x17]; every result pushes
    [2, residual (4 bytes LE), flag]. Drives change 1 ns after the edge (no races)."""
    n, nw = len(vecs), 16 * len(vecs)
    init = []
    for k, v in enumerate(vecs):
        for r, w in enumerate(v["weights"]):
            init.append(f"wt_mem[{16 * k + r}] = 136'h{w:034x};")
        rq = v["requant"]
        init += [f"x_mem[{k}] = 128'h{pack(v['xq'], 8):032x};",
                 f"corr_mem[{k}] = 16'h{v['expected']['corr'] & 0xFFFF:04x};",
                 f"d_mem[{k}] = 3'd{v['D']};",
                 f"s_mem[{k}] = 16'h{pack([1 if s < 0 else 0 for s in v['s']], 1):04x};",
                 f"bud_mem[{k}] = 16'd{v['budget']};",
                 f"sc_mem[{k}] = 128'h{pack(rq['scale'], 8):032x};",
                 f"sh_mem[{k}] = 80'h{pack(rq['shift'], 5):020x};",
                 f"of_mem[{k}] = 128'h{pack(rq['offset'], 8):032x};"]
    pushes = "\n".join(f"            push(code_hi[{8 * j + 7}:{8 * j}]);" for j in range(17)) + "\n" + \
             "\n".join(f"            push(code_lo[{8 * j + 7}:{8 * j}]);" for j in range(17))
    return f"""
    // ---- stimulus: {n} pass(es) {', '.join(v['tag'] for v in vecs)}
    reg [135:0] wt_mem [0:{nw - 1}];
    reg [127:0] x_mem [0:{n - 1}], sc_mem [0:{n - 1}], of_mem [0:{n - 1}];
    reg [79:0]  sh_mem [0:{n - 1}];
    reg [15:0]  corr_mem [0:{n - 1}], s_mem [0:{n - 1}], bud_mem [0:{n - 1}];
    reg [2:0]   d_mem [0:{n - 1}];
    initial begin
        {(chr(10) + '        ').join(init)}
    end

    reg         wt_valid, pass_valid;
    reg [135:0] wt_data;
    reg [127:0] pass_x, cfg_rq_scale, cfg_rq_offset;
    reg [79:0]  cfg_rq_shift;
    reg [15:0]  pass_abft_corr, cfg_abft_s, cfg_abft_budget;
    reg [2:0]   cfg_pkt_d;
    wire        wt_ready, pass_ready, idle, code_valid, res_valid, res_abft_flag, lw_ready;
    wire [135:0] code_hi, code_lo;
    wire [127:0] res_q;
    wire [339:0] res_acc;
    wire [24:0]  res_residual;

    analogioc_top u_top (
        .clk(clk), .rst_n(rst_n),
        .cfg_relu_en(1'b0), .cfg_pkt_d(cfg_pkt_d), .cfg_tile_cnt(4'd1),
        .cfg_abft_s(cfg_abft_s), .cfg_abft_budget(cfg_abft_budget),
        .cfg_rq_scale(cfg_rq_scale), .cfg_rq_shift(cfg_rq_shift), .cfg_rq_offset(cfg_rq_offset),
        .cfg_lora_en(1'b0), .idle(idle),
        .pass_valid(pass_valid), .pass_ready(pass_ready), .pass_x(pass_x), .pass_abft_corr(pass_abft_corr),
        .code_valid(code_valid), .code_hi(code_hi), .code_lo(code_lo),
        .res_valid(res_valid), .res_ready(1'b1), .res_q(res_q), .res_acc(res_acc),
        .res_residual(res_residual), .res_abft_flag(res_abft_flag),
        .lw_valid(1'b0), .lw_ready(lw_ready), .lw_b(1'b0), .lw_idx(4'd0), .lw_code(4'd0),
        .wt_valid(wt_valid), .wt_ready(wt_ready), .wt_data(wt_data)
    );

    integer wk, pk, nres;
    initial begin : weights
        wt_valid = 0; wt_data = 0;
        @(posedge rst_n);
        for (wk = 0; wk < {nw}; wk = wk + 1) begin
            #1 wt_data = wt_mem[wk]; wt_valid = 1;
            @(posedge clk); while (!wt_ready) @(posedge clk);
        end
        #1 wt_valid = 0;
    end
    initial begin : passes
        pass_valid = 0; pass_x = 0; pass_abft_corr = 0;
        cfg_pkt_d = d_mem[0]; cfg_abft_s = s_mem[0]; cfg_abft_budget = bud_mem[0];
        cfg_rq_scale = sc_mem[0]; cfg_rq_shift = sh_mem[0]; cfg_rq_offset = of_mem[0];
        @(posedge rst_n);
        for (pk = 0; pk < {n}; pk = pk + 1) begin
            @(posedge clk); while (!pass_ready) @(posedge clk);
            #1 cfg_pkt_d = d_mem[pk]; cfg_abft_s = s_mem[pk]; cfg_abft_budget = bud_mem[pk];
            cfg_rq_scale = sc_mem[pk]; cfg_rq_shift = sh_mem[pk]; cfg_rq_offset = of_mem[pk];
            pass_x = x_mem[pk]; pass_abft_corr = corr_mem[pk]; pass_valid = 1;
            @(posedge clk); #1 pass_valid = 0;
        end
    end
    initial nres = 0;
    always @(posedge clk) if (rst_n) begin
        if (code_valid) begin
            push(8'd1);
{pushes}
        end
        if (res_valid) begin
            push(8'd2);
            push(res_residual[7:0]); push(res_residual[15:8]); push(res_residual[23:16]);
            push({{7'd0, res_residual[24]}}); push({{7'd0, res_abft_flag}});
            nres = nres + 1;
            if (nres == {n}) fin = 1;
        end
    end
"""


def toy_body():
    """Four 4-phase integ cycles with x_neg = k; col_sign sampled at integ_ack up must
    equal k (the toy macro's comparators). integ_req drops at the A2D crossing of
    integ_ack, so the rawfile shows where the bridge thresholds."""
    return """
    reg       integ_req;
    reg [1:0] x_neg;
    wire      integ_ack;
    wire [1:0] col_sign;
    toymac u_mac (.integ_req(integ_req), .integ_ack(integ_ack), .x_neg(x_neg),
                  .col_sign(col_sign), .vcm());
    integer k;
    initial begin : run
        integ_req = 0; x_neg = 0;
        @(posedge rst_n);
        for (k = 0; k < 4; k = k + 1) begin
            @(posedge clk) #1 x_neg = k;
            @(posedge clk) #1 integ_req = 1;
            @(posedge integ_ack);
            integ_req = 0;
            push(k); push(col_sign);
            @(negedge integ_ack);
        end
        fin = 1;
    end
"""


# --------------------------------------------------------------------------- deck
def deck(ports, macro, macro_spice, dut_v, tstop, rails, models="", save=()):
    """ESPice deck: supplies, rails, the macro subckt, the device. One net per bit."""
    dig = [b for b, d, k in ports if k == "digital"]
    order = [net(b) for b in dig] + OBS
    card = " ".join(f"{k}={v}" for k, v in CARD.items())
    sup = [f"V{b} {b} 0 {0 if b == 'vss' else VDD}" for b, d, k in ports if k == "supply"]
    return "\n".join([
        f"* GENERATED by cosim.py: {macro} SPICE <-> digital RTL (.v device), A2D at vdd/2",
        models,
        f'.include "{macro_spice}"',
        f'.hdl "{dut_v}"',
        *sup, *rails,
        f"Xmac {' '.join(net(b) if k != 'supply' else b for b, d, k in ports)} {macro}",
        f"N1 {' '.join(order)} cosim_dev",
        f".model cosim_dev cosim_dut {card}",
        ".save " + " ".join(f"v({o})" for o in [*OBS, *save]),
        f".tran 0.1n {tstop}",
        ".end", ""])


def real_rails():
    """Ideal refs (CONTRACT "ideal ref territory", INTERFACE.md §2). The ladder spans
    scale with D, and D is the pass's pkt_d: a B-source reads D off the pkt_d pins,
    so a multi-pass run with different D needs no per-pass PWL. Biases: contract
    origin values; refs.json (analog-top agent) overrides any of them by name."""
    import specs
    u, trim, vcm = specs.u_cal(), specs.fine_ref_trim(), specs.VCM_FRAC * VDD
    D = f"((v(pkt_d_0)+2*v(pkt_d_1)+4*v(pkt_d_2))/{VDD})"
    r = {"vcm": vcm,
         "vrn_thrp": vcm, "vrp_thrp": f"{vcm}+15.5*{u}*{D}",
         "vrn_thrn": f"{vcm}-15.5*{u}*{D}", "vrp_thrn": vcm,
         "vrn_sarp": vcm, "vrp_sarp": f"{vcm}+16*{u}*{trim}*{D}",
         "vrn_sarn": f"{vcm}-16*{u}*{trim}*{D}", "vrp_sarn": vcm,
         "vb_nc": 1.25, "vb_pc": 0.29, "vb_tail": 0.665, "vb_ramp": 0.656}
    refs = ROOT / "analog/analogioc/test/refs.json"
    if refs.exists():
        r.update({k: v for k, v in json.loads(refs.read_text()).items() if k in r})
    return [f"B{k} {k} 0 V={v}" if isinstance(v, str) else f"V{k} {k} 0 {v}" for k, v in r.items()]


# --------------------------------------------------------------------------- decode
def read_obs(csv_path):
    """Bytes on obs_d, sampled where obs_v crosses vdd/2; and whether `done` rose."""
    with open(csv_path) as f:
        rows = csv.reader(f)
        head = next(rows)
        ix = {h: i for i, h in enumerate(head)}
        cv, cd = ix["v(obs_v)"], [ix[f"v(obs_d{k})"] for k in range(8)]
        out, prev, done = [], None, False
        for row in rows:
            hi = float(row[cv]) > VDD / 2
            if prev is not None and hi != prev:
                out.append(sum(1 << k for k, c in enumerate(cd) if float(row[c]) > VDD / 2))
            prev = hi
            done |= float(row[ix["v(done)"]]) > VDD / 2
    return out, done


def s8(b):
    return b - 256 if b > 127 else b


def check_real(names, csv_path):
    vecs = pass_vectors(names)
    data, done = read_obs(csv_path)
    codes, res, i = [], [], 0
    while i < len(data):
        if data[i] == 1:
            codes.append(([s8(b) for b in data[i + 1:i + 18]], [s8(b) for b in data[i + 18:i + 35]]))
            i += 35
        elif data[i] == 2:
            r = int.from_bytes(bytes(data[i + 1:i + 5]), "little")
            res.append((r - (1 << 25) if r >> 24 else r, data[i + 5]))
            i += 6
        else:
            raise AssertionError(f"obs stream: bad tag {data[i]} at byte {i}")
    ok = done and len(codes) == len(vecs) and len(res) == len(vecs)
    print(f"cosim: done={done}, {len(codes)} code records, {len(res)} results for {len(vecs)} passes")
    for v, (hi, lo), (resid, flag) in zip(vecs, codes, res):
        ex = v["expected"]
        err = [abs(a - b) for a, b in zip(hi + lo, ex["code_hi"] + ex["code_lo"])]
        good = max(err) <= CODE_TOL and abs(resid) <= v["budget"]
        ok &= good
        print(f"  {v['tag']}: max|code err| {max(err)} LSB (tol {CODE_TOL}), {sum(e > 1 for e in err)}/34 "
              f"codes outside +-1, residual {resid} (budget {v['budget']}), flag {flag}: "
              f"{'PASS' if good else 'FAIL'}")
    print("COSIM PASS" if ok else "COSIM FAIL")
    return ok


# --------------------------------------------------------------------------- commands
def run(cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(list(map(str, cmd)), cwd=OUT).returncode


def smoke():
    """Toy macro: RC + comparator B-sources (no PDK), through the same generator."""
    ports = read_ports(HERE / "toy/toymac.ports")
    (OUT / "smoke").mkdir(parents=True, exist_ok=True)
    (OUT / "smoke/dut.v").write_text(device_verilog(ports, "toymac", "u_mac", toy_body()))
    (OUT / "smoke/smoke.sp").write_text(deck(ports, "toymac", HERE / "toy/toymac.spice", "dut.v", "500n",
                                             ["Vvcm vcm 0 0.9"], save=["integ_req", "integ_ack"]))
    rc = subprocess.run([ESPICE, "smoke.sp", "--format=csv", "--rawfile", "smoke.csv"], cwd=OUT / "smoke").returncode
    assert rc == 0, f"espice exit {rc}"
    data, done = read_obs(OUT / "smoke/smoke.csv")
    pairs = list(zip(data[0::2], data[1::2]))
    print(f"smoke: obs bytes {data}, done={done}")
    assert done and pairs == [(k, k) for k in range(4)], f"col_sign != x_neg per cycle: {pairs}"
    # bridge edges: integ_req ramps 10-90 % in ~0.8 trise; it starts falling where
    # integ_ack crosses vdd/2 (A2D threshold), give or take ttol and one time step
    with open(OUT / "smoke/smoke.csv") as f:
        rows = csv.DictReader(f)
        t, req, ack = zip(*((float(r["time"]), float(r["v(integ_req)"]), float(r["v(integ_ack)"])) for r in rows))
    t10 = next(t[i] for i in range(len(t)) if req[i] > 0.1 * VDD)
    t90 = next(t[i] for i in range(len(t)) if req[i] > 0.9 * VDD)
    top = max(req)
    fall = next(i for i in range(len(t)) if t[i] > t90 and req[i] < top - 0.02)
    print(f"smoke: integ_req rise 10-90 % {1e12 * (t90 - t10):.0f} ps (trise {CARD['trise']}); "
          f"v(integ_ack) where integ_req starts falling {ack[fall - 1]:.3f} V (vth {CARD['vth']})")
    assert 50e-12 < t90 - t10 < 400e-12, "D2A ramp is not ~trise"
    assert abs(ack[fall - 1] - VDD / 2) < 0.2, "A2D did not switch near vdd/2"
    print("COSIM SMOKE PASS")


def gen(names):
    vecs = pass_vectors(names)
    ports = read_ports(ROOT / "analog/analogioc/netlist/analogioc.ports")
    rtl = sorted(p for p in (ROOT / "digital/analogioc/src").glob("*.v") if p.name != "rail_top.v")
    OUT.mkdir(parents=True, exist_ok=True)
    # one .hdl file: the device top, the macro shell, then the RTL it instantiates
    (OUT / "cosim_dut.v").write_text(device_verilog(ports, "analogioc", "u_top.u_analogioc", real_body(vecs))
                                     + "".join(p.read_text() for p in rtl))
    import specs
    tstop = os.environ.get("TSTOP", f"{12 * len(vecs)}u")   # ponytail: ~2x a pass at TQ_SIM; raise on timeout
    (OUT / "cosim.sp").write_text(deck(ports, "analogioc", ROOT / "analog/analogioc/netlist/analogioc.spice",
                                       "cosim_dut.v", tstop, real_rails(),
                                       specs.get_pdk().lib_line(os.environ.get("CORNER", "tt"))))
    print(f"cosim: wrote {OUT}/cosim_dut.v, {OUT}/cosim.sp ({', '.join(v['tag'] for v in vecs)}; "
          f"{sum(1 for p in ports if p[2] == 'digital') + len(OBS)} device pins, tstop {tstop})")


def elab():
    """VerA builds cosim_dut as a contract device (no zig compile, no simulation)."""
    return run([VERA, "--emit-zig", "-o", "cosim_dut.zig", "cosim_dut.v"])


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    passes = args or ["05"]
    if cmd == "smoke":
        smoke()
    elif cmd == "gen":
        gen(passes)
    elif cmd == "elab":
        sys.exit(elab())
    elif cmd == "check":
        sys.exit(0 if check_real(passes, OUT / "cosim.csv") else 1)
    else:
        sys.exit(__doc__)

"""sysreference PPA on ASAP7 RVT: yosys synth -> OpenROAD placement + RC -> OpenSTA
timing and VCD power -> build/ppa.json.

    python3 scripts/ppa.py synth     # area sweep, every config, TT  (yosys)
    python3 scripts/ppa.py place     # s8 TT/FF/SS + s16 TT: place, CTS, RC, fmax (openroad)
    python3 scripts/ppa.py power     # s16 gate-level sim VCD -> report_power (iverilog, openroad)
    python3 scripts/ppa.py report    # ppa.json + array/die numbers (python only)
    python3 scripts/ppa.py all

Tools: yosys, iverilog, openroad, python3+numpy (Makefile runs it in nix-shell).
Cells: asap7sc7p5t_28 RVT, all three corners (TT 0.7 V 25 C is the scoring corner).
"""
import json
import numpy as np
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BLK = Path(__file__).resolve().parents[1]
SRC = sorted(str(p) for p in (BLK / "src").glob("*.sv"))
OUT = BLK / "build" / "ppa"
SC = Path(os.environ.get(
    "ASAP7_SC", "/nix/store/aqsh7rn2wrfv2j5902bgk88xx9f62jqi-asap7sc7p5t-28-unstable-2026-09-30"
    "/asap7/libs.ref/asap7sc7p5t"))
ORFS_T = Path(os.environ.get(
    "ASAP7_ORFS_TEST", "/nix/store/b7bw499jgql9p2n7hz2fbx5hk4zicyz0-source/test/asap7"))
CORNERS = {"TT": "TT", "FF": "FF", "SS": "SS"}
# ponytail: one SIMPLE date per corner; FF has a 250407 respin we ignore for corner parity
LIBS = ("AO_RVT_{c}_nldm_211120", "INVBUF_RVT_{c}_nldm_220122", "OA_RVT_{c}_nldm_211120",
        "SIMPLE_RVT_{c}_nldm_211120", "SEQ_RVT_{c}_nldm_220123")
# usual asap7 platform dont-use: fractional drive strengths and scan flops
DONT = ("*x1p*_ASAP7*", "*xp*_ASAP7*", "SDF*", "ICG*")

CONFIGS = {f"s{n}": dict(Rows=n, Cols=n, AccDepth=n) for n in (8, 16, 32)}
CONFIGS["s16_int4w"] = dict(Rows=16, Cols=16, AccDepth=16, WW=4)
CONFIGS["s16_nopipe"] = dict(Rows=16, Cols=16, AccDepth=16, PipeMul=0)
CONFIGS["s16_nocg"] = dict(Rows=16, Cols=16, AccDepth=16, _cg=0)
CONFIGS["s16_nobooth"] = dict(Rows=16, Cols=16, AccDepth=16, _booth=0)
# ponytail: s64/s128 are not synthesized (s128 ran > 45 min); array area is fit to s8/s16/s32
PERIOD_PS = 400   # abc delay target; fmax comes from STA, not from this


def libs(corner):
    return [str(SC / "lib" / f"asap7sc7p5t_{n.format(c=corner)}.lib") for n in LIBS]


def sh(cmd, log):
    with open(log, "w") as f:
        subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.STDOUT)


def synth(name, params, corner="TT"):
    """Hierarchical (each PE variant mapped once); clock gating via the ICG cells."""
    p = dict(params)
    booth, cg = p.pop("_booth", 1), p.pop("_cg", 1)
    adder = p.pop("_adder", "kogge-stone")   # yosys default is ripple carry
    d = OUT / "synth"
    d.mkdir(parents=True, exist_ok=True)
    lp = libs(corner)
    la = " ".join(f"-liberty {x}" for x in lp)
    dont = " ".join(f"-dont_use {x}" for x in DONT)
    chp = " ".join(f"-set {k} {v}" for k, v in p.items())
    tag = f"{name}_{corner}"
    script = f"""
read_liberty -lib {' '.join(lp)}
read_verilog -defer -sv {' '.join(SRC)}
{f'chparam {chp} sa_top' if chp else ''}
hierarchy -top sa_top
synth -top sa_top {'-booth' if booth else ''} -run :fine
techmap -map +/techmap.v {"" if adder == "ripple" else f"-map +/choices/{adder}.v"}
synth -top sa_top -run fine:
{f'clockgate -liberty {lp[-1]} -min_net_size 4' if cg else ''}
dfflibmap -liberty {lp[-1]} {dont}
abc -D {PERIOD_PS} {la} {dont}
hilomap -singleton -hicell TIEHIx1_ASAP7_75t_R H -locell TIELOx1_ASAP7_75t_R L
opt_clean -purge
tee -q -o {d}/{tag}.stat.json stat -json -top sa_top {la}
write_verilog -noattr -noexpr {d}/{tag}.v
"""
    (d / f"{tag}.ys").write_text(script)
    sh(["yosys", "-q", "-s", str(d / f"{tag}.ys")], d / f"{tag}.log")
    st = json.loads((d / f"{tag}.stat.json").read_text())
    top = st["design"]
    cells = top.get("num_cells_by_type", {})
    res = dict(name=name, corner=corner, params=p, booth=bool(booth), clock_gating=bool(cg),
               adder=adder,
               area_um2=top["area"], cells=top["num_cells"],
               flops=sum(v for k, v in cells.items() if k.startswith("DFF")),
               icgs=sum(v for k, v in cells.items() if k.startswith("ICG")),
               area_by_module={m.strip("\\"): v.get("area") for m, v in st["modules"].items()},
               count_by_module={m.strip("\\"): v.get("num_cells")
                                for m, v in st["modules"].items()})
    (d / f"{tag}.json").write_text(json.dumps(res, indent=1))
    print(f"synth {tag:16s} area {top['area']:12.1f} um2 cells {top['num_cells']:8d}", flush=True)
    return res


def cmd_synth():
    jobs = [(n, p, "TT") for n, p in CONFIGS.items()]
    jobs += [(n, CONFIGS[n], c) for n in ("s8", "s16") for c in ("FF", "SS")]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for f in [ex.submit(synth, *j) for j in jobs]:
            f.result()


# ------------------------------------------------------------------ placement + CTS + STA
def place_tcl(name, corner, period_ps):
    """Floorplan at 60 % utilization, global + detailed placement, RC from the ORFS asap7
    setRC (correlated on aes/ibex/cva6), repair_design, CTS with propagated clock,
    repair_timing to the target period. No routing: parasitics are placement estimates."""
    d = OUT / "place"
    tag = f"{name}_{corner}"
    lib_lines = "\n".join(f"read_liberty {x}" for x in libs(corner))
    return f"""
{lib_lines}
read_lef {SC}/techlef/asap7_tech_1x_201209.lef
read_lef {SC}/lef/asap7sc7p5t_28_R_1x_220121a.lef
read_verilog {OUT}/synth/{tag}.v
link_design sa_top
create_clock -name clk -period {period_ps} [get_ports clk_i]
set_input_delay  [expr {period_ps} * 0.2] -clock clk [delete_from_list [all_inputs] [get_ports clk_i]]
set_output_delay [expr {period_ps} * 0.2] -clock clk [all_outputs]
set_load 1.0 [all_outputs]
set_false_path -from [get_ports rst_ni]
initialize_floorplan -utilization 60 -aspect_ratio 1 -core_space 2 -site asap7sc7p5t
source {ORFS_T}/asap7.tracks.tcl
place_pins -hor_layers M4 -ver_layers M5
global_placement -density 0.65 -skip_io
source {ORFS_T}/setRC.tcl
estimate_parasitics -placement
repair_design
detailed_placement
clock_tree_synthesis -root_buf BUFx4_ASAP7_75t_R -buf_list BUFx4_ASAP7_75t_R -sink_clustering_enable
set_propagated_clock [all_clocks]
detailed_placement
estimate_parasitics -placement
repair_timing -setup -skip_pin_swap
detailed_placement
estimate_parasitics -placement
report_checks -path_delay max -group_path_count 1 -format full_clock_expanded -digits 1 > {d}/{tag}.timing.rpt
report_wns > {d}/{tag}.wns.rpt
report_tns >> {d}/{tag}.wns.rpt
report_design_area
report_power > {d}/{tag}.power_novcd.rpt
write_db {d}/{tag}.odb
write_verilog {d}/{tag}.v
exit
"""


PERIODS = {"TT": 800, "FF": 600, "SS": 1400}


def place(name, corner):
    d = OUT / "place"
    d.mkdir(parents=True, exist_ok=True)
    period_ps = PERIODS[corner]
    tcl = d / f"{name}_{corner}.tcl"
    log = tcl.with_suffix(".log")
    # ponytail: resume = reuse a finished run (odb written after the reports)
    if not ((d / f"{name}_{corner}.odb").exists() and "Design area" in
            (log.read_text() if log.exists() else "")):
        tcl.write_text(place_tcl(name, corner, period_ps))
        sh(["openroad", "-no_init", "-exit", str(tcl)], log)
    # fmax from register-to-register paths: the port paths see the full clock insertion
    # delay against an ideal external clock, an artifact of a block with no neighbours
    # (in sa_sys the ports face SRAM macros clocked off the same tree).
    r2r = d / f"{name}_{corner}.r2r.rpt"
    if not r2r.exists():
        t = d / f"{name}_{corner}.r2r.tcl"
        t.write_text("\n".join(f"read_liberty {x}" for x in libs(corner)) + f"""
read_db {d}/{name}_{corner}.odb
create_clock -name clk -period {period_ps} [get_ports clk_i]
set_propagated_clock [all_clocks]
source {ORFS_T}/setRC.tcl
estimate_parasitics -placement
report_checks -path_delay max -from [all_registers] -to [all_registers] -format full_clock_expanded -digits 1 > {r2r}
exit
""")
        sh(["openroad", "-no_init", "-exit", str(t)], t.with_suffix(".log"))
    io_rpt = (d / f"{name}_{corner}.timing.rpt").read_text()
    io_wns = float(re.search(r"(-?[\d.]+)\s+slack \(", io_rpt).group(1))
    rpt = r2r.read_text()
    wns = float(re.search(r"(-?[\d.]+)\s+slack \(", rpt).group(1))
    area = float(re.findall(r"Design area ([\d.]+) um\^2", tcl.with_suffix(".log").read_text())[-1])
    # fmax = 1 / (period - wns): exact when wns < 0, a slack-implied estimate when wns > 0
    fmax = 1e6 / (period_ps - wns)
    res = dict(name=name, corner=corner, period_ps=period_ps, wns_ps=wns, fmax_mhz=fmax,
               io_wns_ps=io_wns, fmax_mhz_with_io=1e6 / (period_ps - io_wns),
               cell_area_um2=area,
               startpoint=re.search(r"Startpoint: (\S+)", rpt).group(1),
               endpoint=re.search(r"Endpoint: (\S+)", rpt).group(1))
    (d / f"{name}_{corner}.json").write_text(json.dumps(res, indent=1))
    print(f"place {name}_{corner}: wns {wns} ps @ {period_ps} ps -> fmax {fmax:.0f} MHz "
          f"({res['startpoint']} -> {res['endpoint']})", flush=True)
    return res


def cmd_place():
    # ponytail: serial; another openroad on this box holds ~15 GB
    for name, corner in (("s8", "TT"), ("s8", "FF"), ("s8", "SS"), ("s16", "TT")):
        place(name, corner)


# ------------------------------------------------------------------ gate-level VCD power
def cells_v(corner="TT"):
    """Zero-delay iverilog models generated from the liberty `function`s. The vendor
    models route data through $setuphold delayed_* nets, which iverilog leaves undriven.
    Flops get a 5 ps clk->q so gated-clock delta skew cannot race."""
    out = OUT / "power" / "cells.v"
    out.parent.mkdir(parents=True, exist_ok=True)
    mods = ["`timescale 1ns/1ps"]
    for lib in libs(corner):
        for cell in re.split(r"\n\s*cell\s*\(", Path(lib).read_text())[1:]:
            name = cell.split(")")[0].strip().strip('"')
            pins = re.findall(r'pin\s*\(\s*"?(\w+)"?\s*\)\s*\{(.*?)(?=\n\s*pin\s*\(|\Z)', cell, re.S)
            ins = [n for n, b in pins if re.search(r"direction\s*:\s*input", b)]
            outs = [(n, re.search(r'function\s*:\s*"([^"]*)"', b))
                    for n, b in pins if re.search(r"direction\s*:\s*output", b)]
            ports = ", ".join(ins + [n for n, _ in outs])
            hdr = f"module {name} ({ports});\n" + "".join(f" input {n};\n" for n in ins) + \
                "".join(f" output {n};\n" for n, _ in outs)
            if name.startswith("DFFHQN"):
                body = " reg q; always @(posedge CLK) q <= #0.005 D; assign QN = ~q;\n"
            elif name.startswith("DFFASRHQN"):
                body = (" reg q; always @(posedge CLK or negedge RESETN or negedge SETN)\n"
                        "  if (!RESETN) q <= #0.005 1'b0; else if (!SETN) q <= #0.005 1'b1;"
                        " else q <= #0.005 D;\n assign QN = ~q;\n")
            elif name.startswith("ICG"):
                body = " reg en; always @* if (!CLK) en = ENA | SE; assign GCLK = CLK & en;\n"
            elif all(f and "IQ" not in f.group(1) for _, f in outs):
                body = "".join(f" assign {n} = {f.group(1).replace('*', '&').replace('+', '|').replace('!', '~')};\n"
                               for n, f in outs)
            else:
                continue   # other sequential cells: not produced by this flow
            mods.append(hdr + body + "endmodule")
    out.write_text("\n".join(mods) + "\n")
    return out


def power_case(name, job, tag="s16_TT"):
    """RTL-checked stimulus -> gate-level sim of the synthesized netlist (also a GL
    functional check) -> VCD -> OpenSTA report_power on the placed+CTS design."""
    sys.path.insert(0, str(BLK / "test"))
    import run_tests as RT
    import sched as S
    d = OUT / "power" / name
    d.mkdir(parents=True, exist_ok=True)
    cfg = S.Cfg()
    assert RT.run_case(name, cfg, [job], vcd_dir=d), "RTL check of the power stimulus failed"
    ncyc = len((d / "stim.hex").read_text().split())
    nexp = len((d / "exp.hex").read_text().split())
    pargs = [f"-Ptb_sa_top.{k}={v}" for k, v in
             dict(Rows=16, Cols=16, WW=8, AccDepth=16, PipeMul=1, NCyc=ncyc, NExp=nexp).items()]
    vvp = d / "gl.vvp"
    sh(["iverilog", "-g2012", "-DGL", "-o", str(vvp), *pargs, f'-Ptb_sa_top.Dir="{d}"',
        str(BLK / "test" / "tb_sa_top.sv"), str(OUT / "synth" / f"{tag}.v"), str(cells_v())],
       d / "gl_build.log")
    sh(["vvp", "-n", str(vvp), "+vcd"], d / "gl_sim.log")
    log = (d / "gl_sim.log").read_text()
    gl_pass = "PASS" in log and "FAIL" not in log
    assert gl_pass, f"gate-level sim of {tag} disagrees with the golden: {d}/gl_sim.log"
    # OpenSTA's VCD reader rejects $dumpon/$dumpoff: keep the window, drop the markers
    with open(d / "sa.vcd") as src, open(d / "sa_sta.vcd", "w") as dst:
        in_on = False
        for line in src:
            if line.startswith("$dumpoff"):
                break
            if line.startswith("$dumpon"):
                in_on = True
            elif in_on and line.startswith("$end"):
                in_on = False
            else:
                dst.write(line)
    (d / "sa.vcd").unlink()
    period_ps = 2000      # tb clock: #1 half period at 1 ns timescale
    tcl = d / "power.tcl"
    tcl.write_text(f"""
{chr(10).join(f"read_liberty {x}" for x in libs("TT"))}
read_db {OUT}/place/{tag}.odb
create_clock -name clk -period {period_ps} [get_ports clk_i]
set_propagated_clock [all_clocks]
source {ORFS_T}/setRC.tcl
estimate_parasitics -placement
read_vcd -scope tb_sa_top/dut {d}/sa_sta.vcd
report_power -digits 6 > {d}/power.rpt
report_power -instances [get_cells *] -digits 9 > {d}/power_inst.rpt
exit
""")
    sh(["openroad", "-no_init", "-exit", str(tcl)], d / "power.log")
    tot = re.search(r"^Total\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)",
                    (d / "power.rpt").read_text(), re.M)
    p_int, p_sw, p_leak, p_tot = (float(x) for x in tot.groups())
    grp = dict(pe=[0.0, 0.0], edge=[0.0, 0.0], clock=[0.0, 0.0], other=[0.0, 0.0])
    for line in (d / "power_inst.rpt").read_text().splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        try:
            dyn, leak = float(f[0]) + float(f[1]), float(f[2])
        except ValueError:
            continue
        inst = f[-1]
        g = ("pe" if "u_pe" in inst else "edge" if "u_edge" in inst
             else "clock" if inst.startswith(("clkbuf", "clkload", "clone")) and "clk" in inst else "other")
        grp[g][0] += dyn
        grp[g][1] += leak
    macs = int(job["X"].shape[0] * job["X"].shape[1] * job["W"].shape[1])
    t_win = ncyc * period_ps * 1e-12
    res = dict(case=name, design=tag, gl_sim_pass=gl_pass, cycles=ncyc, macs=macs,
               util=macs / (ncyc * 256), vcd_clock_mhz=1e6 / period_ps,
               p_dyn_w=p_int + p_sw, p_leak_w=p_leak, p_total_w=p_tot,
               e_dyn_per_mac_fj=(p_int + p_sw) * t_win / macs * 1e15,
               dyn_split_fj_per_mac={k: v[0] * t_win / macs * 1e15 for k, v in grp.items()},
               leak_split_w={k: v[1] for k, v in grp.items()})
    (d / "power.json").write_text(json.dumps(res, indent=1))
    print(f"power {name}: GL {'PASS' if gl_pass else 'FAIL'} util {res['util']:.3f} "
          f"E_dyn {res['e_dyn_per_mac_fj']:.1f} fJ/MAC leak {p_leak*1e3:.3f} mW "
          f"split {({k: round(v, 1) for k, v in res['dyn_split_fj_per_mac'].items()})}", flush=True)
    return res


def real_power_job():
    """SmolLM2 blk.0 attn_q real INT8 weights/activations, cut to a 32 x 128 x 48 GEMM
    (the 9 prompt tokens' activation slices at 4 channel offsets make 32 real rows)."""
    sys.path.insert(0, str(BLK / "test"))
    import run_tests as RT
    j = RT.real_job()
    X = np.concatenate([j["X"][:, o:o + 128] for o in (0, 128, 256, 384)])[:32]
    n = slice(0, 48)
    return dict(X=X, W=j["W"][:128, n], scale=j["scale"][n], shift=j["shift"][n],
                offset=j["offset"][n])


def cmd_power():
    sys.path.insert(0, str(BLK / "test"))
    import run_tests as RT
    rng = np.random.default_rng(7)
    power_case("rand_dense", RT.rand_job(rng, 32, 128, 48))
    power_case("smollm2_real", real_power_job())


# ------------------------------------------------------------------ report
# SRAM model: fakeram7_256x32 (ORFS asap7 test set; a CACTI-style placeholder macro, not a
# compiled bitcell array): area from the fakeram7 LEFs, energy/leakage from its liberty.
FAKERAM_LEF_UM2 = {(256, 32): 8.36 * 42.0, (64, 256): 33.25 * 46.8, (256, 256): 33.25 * 84.0,
                   (2048, 39): 20.33 * 166.6}
SRAM_E_ACCESS_PJ = 2 * 1.345      # clk rise + fall internal energy, 256x32, per access
SRAM_LEAK_UW = 128.9              # 256x32


def cmd_report(N=128):
    syn = {n: json.loads((OUT / "synth" / f"{n}_TT.json").read_text()) for n in CONFIGS}
    pl = {p.stem: json.loads(p.read_text()) for p in (OUT / "place").glob("*.json")}
    pw = {p.parent.name: json.loads(p.read_text()) for p in (OUT / "power").glob("*/power.json")}

    def pe_area(s):
        a = [v for k, v in s["area_by_module"].items() if k.endswith("sa_pe")]
        return float(np.mean(a)) if a else None

    def edge_area(s):
        return next(v for k, v in s["area_by_module"].items() if k.endswith("sa_edge"))

    # array cell area A(n) = a n^2 + b n + c fit through s8/s16/s32 (exact 3-point fit)
    ns = np.array([8, 16, 32])
    A = np.array([syn[f"s{n}"]["area_um2"] for n in ns])
    coef = np.polyfit(ns, A, 2)
    area_N = float(np.polyval(coef, N))
    util = 0.70   # placement utilization for the footprint (s16 placed at 60 % here)
    s16 = syn["s16"]
    pe16, edge16 = pe_area(s16), edge_area(s16)
    other16 = s16["area_um2"] - 256 * pe16 - 16 * edge16
    fmax = {k: v["fmax_mhz"] for k, v in pl.items()}
    f_tt = pl.get("s16_TT", pl.get("s8_TT", {})).get("fmax_mhz")
    real = pw.get("smollm2_real") or {}
    rnd = pw.get("rand_dense") or {}
    # energy/MAC at N x N (derived): PE + array-proportional parts constant per MAC,
    # the edge (one requant per token per column) amortized over N rows instead of 16
    def e_at(p, n):
        s = p["dyn_split_fj_per_mac"]
        return s["pe"] + s["other"] + s["clock"] + s["edge"] * 16 / n
    leak16 = (real or rnd).get("p_leak_w")
    leak_pe = leak16 / s16["area_um2"] * (area_N / N**2) if leak16 else None
    e_mac = e_at(real, N) if real else None
    gops = 2 * N * N * f_tt * 1e6 / 1e12 if f_tt else None
    p_N = (e_mac * 1e-15 * N * N * f_tt * 1e6 + leak_pe * N * N) if e_mac and f_tt else None
    sram_bits = 1 << 20
    ppa = dict(
        label="measured: yosys/ASAP7 RVT synth, OpenROAD place+CTS+STA, OpenSTA VCD power at "
              "s8/s16/s32; derived: everything at array_rows x array_cols",
        corner="TT 0.7 V 25 C (asap7sc7p5t_28 RVT TT nldm)",
        array_rows=N, array_cols=N,
        area_um2_per_pe=area_N / util / N**2,
        area_um2_per_pe_cell_only=area_N / N**2,
        fmax_mhz=f_tt,
        energy_per_mac_fJ=e_mac,
        energy_per_mac_fJ_random_data=e_at(rnd, N) if rnd else None,
        leak_W_per_pe=leak_pe,
        notes=dict(
            area_um2_per_pe=f"derived: quadratic fit of synthesized cell area (s8/s16/s32) at "
                            f"N={N}, / {util} placement utilization; includes edge accumulators, "
                            f"requant, skew/deskew, input regs, clock gating",
            fmax_mhz="measured: s16 TT after placement + CTS + repair_timing, placement RC "
                     "(no detailed route); 128x128 broadcast nets not checked (projected same "
                     "with one extra weight-bus pipeline stage)",
            energy_per_mac_fJ="derived from measured s16 gate-level VCD power on SmolLM2 real "
                              "INT8 data; edge share scaled 16/N; excludes SRAM and HBM; "
                              "open-source flow (no power-aware sizing, placement RC): an upper "
                              "bound, a commercial flow is expected lower",
            power_density="derived: 128x128 at fmax is ~2.3 W/mm2, over the 1 W/mm2 "
                          "ARCH_METRIC cap; the scorer must derate clock/VDD",
        ),
        measured=dict(
            synth_area_um2={k: v["area_um2"] for k, v in syn.items()},
            pe_cell_area_um2={k: pe_area(v) for k, v in syn.items()},
            s16_edge_area_um2_per_col=edge16,
            s16_other_area_um2=other16,
            area_fit_um2_n2_n_1=[float(c) for c in coef],
            fmax_mhz=fmax, place=pl, power=pw,
            synth_corner_area_um2={f"{n}_{c}": json.loads((OUT / "synth" / f"{n}_{c}.json")
                                   .read_text())["area_um2"]
                                   for n in ("s8", "s16") for c in ("TT", "FF", "SS")
                                   if (OUT / "synth" / f"{n}_{c}.json").exists()},
        ),
        array=dict(
            label="derived",
            rows=N, cols=N, cell_area_mm2=area_N / 1e6, footprint_mm2=area_N / util / 1e6,
            peak_tops=gops, power_w_at_fmax=p_N,
            tops_per_w=gops / p_N if p_N else None,
            tops_per_mm2=gops / (area_N / util / 1e6) if gops else None,
            arrays_per_100mm2_logic_only=1e8 / (area_N / util),
        ),
        sram_model=dict(
            label="projected: fakeram7 (CACTI-style placeholder, ORFS asap7 test set), uncalibrated",
            area_um2_per_bit={f"{d}x{w}": a / (d * w) for (d, w), a in FAKERAM_LEF_UM2.items()},
            read_energy_fJ_per_bit=SRAM_E_ACCESS_PJ * 1e3 / 32,
            leak_nW_per_bit=SRAM_LEAK_UW * 1e3 / (256 * 32),
            example_1Mbit_mm2=sram_bits * FAKERAM_LEF_UM2[(256, 256)] / 65536 / 1e6,
            per_mac_fJ_at_N=dict(activation_read=SRAM_E_ACCESS_PJ * 1e3 / 32 * 8 / N,
                                 output_write=SRAM_E_ACCESS_PJ * 1e3 / 32 * 8 / 1024,
                                 note="activation byte read once per row per token, used by "
                                      "N columns; INT8 output written once per K (>= 1024 here); "
                                      "weights stream from HBM (ARCH_METRIC) and are charged there"),
        ),
    )
    (BLK / "build" / "ppa.json").write_text(json.dumps(ppa, indent=1))
    print(json.dumps({k: ppa[k] for k in ("area_um2_per_pe", "fmax_mhz", "energy_per_mac_fJ",
                                          "leak_W_per_pe", "array")}, indent=1))


if __name__ == "__main__":
    cmds = dict(synth=cmd_synth, place=cmd_place, power=cmd_power, report=cmd_report)
    for c in (sys.argv[1:] or ["synth"]):
        if c == "all":
            for f in cmds.values():
                f()
        else:
            cmds[c]()

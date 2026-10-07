"""Stimulus generator for imc_driver: one job -> Verilog memories + HBM model + driver + tiles.

The same body is wrapped two ways:
  tb_<name>.v   iverilog unit test: ideal behavioural tiles (imc_tile_beh.v), self-checking against
                the bit-true golden (scripts/golden/imc_tile.py), prints PASS/FAIL
  cosim_dut     ESPice .v device (analog/imc_tile/test/tb_cosim.py): the tiles are the Verilog-A
                netlist outside the device; results leave on obs pins
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from golden import imc_tile as G   # noqa: E402

SRC = [str(p) for p in sorted((HERE.parent / "src").glob("*.v"))]
HALF_PS = 71                      # tick 142 ps: ml2 slot 8 ticks = 1.136 ns (P 1.132 ns)


@dataclass
class Cfg:
    rows: int = 8
    cols: int = 8
    ntiles: int = 2
    adc_share: int = 4
    bits: int = 12
    mode: str = "ml2"
    acc_depth: int = 16
    hbm_lat: int = 4              # ticks before the first row
    hbm_gap: int = 1              # ticks per row word (1 = a row per tick)
    code_shift: int = 6           # log2(lsb_mac)
    refresh: int = 128            # passes between gain-cell refresh rewrites (B1 retention)

    def params(self):
        """Golden parameters that match this RTL configuration."""
        return G.P(rows=self.rows, cols=self.cols, mode=self.mode, adc_share=self.adc_share,
                   adc_bits=self.bits, lsb_mac=1 << self.code_shift, t_tick=2 * HALF_PS / 1000)

    def vparams(self):
        p = self.params()
        return dict(Rows=self.rows, Cols=self.cols, NTiles=self.ntiles, AdcShare=self.adc_share,
                    Bits=self.bits, Mode=0 if self.mode == "ml2" else 1, SlotTicks=p.slot_ticks(),
                    RstTicks=p.rst_ticks, ShTicks=p.sh_ticks, MergeTicks=p.merge_ticks,
                    RoundTicks=p.round_ticks, CodeShift=self.code_shift, AccDepth=self.acc_depth,
                    RefreshPasses=self.refresh)


def hexw(vals, width):
    m = (1 << width) - 1
    return sum((int(v) & m) << (width * i) for i, v in enumerate(vals))


def layout(cfg, job):
    """Pad the job onto the array; return the streams, tables and the ideal-golden expectation."""
    R, C, N = cfg.rows, cfg.cols, cfg.ntiles
    X, W = np.asarray(job["X"], np.int64), np.asarray(job["W"], np.int64)
    M, K = X.shape
    Nout = W.shape[1]
    kq = R * N
    Kp, Np = -(-K // kq) * kq, -(-Nout // C) * C
    Xp = np.zeros((M, Kp), np.int64); Xp[:, :K] = X
    Wp = np.zeros((Kp, Np), np.int64); Wp[:K, :Nout] = W
    G_, NB = Kp // kq, Np // C
    pad = lambda v: np.concatenate([np.asarray(v, np.int64), np.zeros(Np - Nout, np.int64)])
    sc, sh, of = pad(job["scale"]), pad(job["shift"]), pad(job["offset"])
    D = cfg.acc_depth
    MC = -(-M // D)
    x_words = [hexw(Xp[m, c * R:(c + 1) * R], 8) for m in range(M) for c in range(Kp // R)]
    w_rows = [hexw(Wp[(kg * N + t) * R + r, nb * C:(nb + 1) * C], 8)
              for nb in range(NB) for mc in range(MC) for kg in range(G_) for t in range(N) for r in range(R)]
    rq = [hexw([(int(sc[c]) & 0xFF) | ((int(sh[c]) & 0x1F) << 8) | ((int(of[c]) & 0xFF) << 13)
                for c in range(nb * C, (nb + 1) * C)], 21) for nb in range(NB)]
    p = cfg.params()
    acc, _ = G.gemm(Xp, Wp, p)                       # ideal codes, identity cal
    y8 = G.requant(acc, p, sc, sh, of)
    exp = [(m, nb, acc[m, nb * C:(nb + 1) * C], y8[m, nb * C:(nb + 1) * C])
           for nb in range(NB) for m in range(M)]
    return dict(M=M, G=G_, NB=NB, x=x_words, w=w_rows, rq=rq, exp=exp, Np=Np, Kp=Kp)


def body(cfg, L, target, cal=None, replay=None, trace=False):
    """Verilog body: memories, HBM model, driver, tiles, output check.
    target "beh": ideal behavioural tiles, or with replay=(dir, n_rounds) the codes ESPice produced;
    trace=True dumps every tile-facing pin at both clock edges (the PWL stimulus for ESPice)."""
    v = cfg.vparams()
    R, C, N = cfg.rows, cfg.cols, cfg.ntiles
    NC, B = C // cfg.adc_share, cfg.bits
    init = [f"x_mem[{i}] = {R*8}'h{w:x};" for i, w in enumerate(L["x"])]
    init += [f"w_mem[{i}] = {C*8}'h{w:x};" for i, w in enumerate(L["w"])]
    init += [f"rq_mem[{i}] = {C*21}'h{w:x};" for i, w in enumerate(L["rq"])]
    for k, (m, nb, a, y) in enumerate(L["exp"]):
        init.append(f"ea_mem[{k}] = {C*24}'h{hexw(a, 24):x}; ey_mem[{k}] = {C*8}'h{hexw(y, 8):x}; "
                    f"em_mem[{k}] = {m}; enb_mem[{k}] = {nb};")
    cal = cal or []
    init += [f"cg_mem[{i}] = 16'd{g}; co_mem[{i}] = 20'h{int(o) & 0xFFFFF:x};" for i, (g, o) in enumerate(cal)]
    pv = ", ".join(f".{k}({val})" for k, val in v.items())
    nx, nw, ne = len(L["x"]), len(L["w"]), len(L["exp"])
    tiles = ""
    if target == "beh":
        mod = (lambda t: f"imc_tile_replay #(.Rows({R}), .Cols({C}), .AdcShare({cfg.adc_share}), .Bits({B}), "
                         f".NRounds({replay[1]}), .FILE(\"{replay[0]}/codes_{t}.hex\"))") if replay else \
              (lambda t: f"imc_tile_beh #(.Rows({R}), .Cols({C}), .AdcShare({cfg.adc_share}), .Bits({B}), "
                         f".Mode({v['Mode']}), .CodeShift({cfg.code_shift}))")
        tiles = "\n".join(
            f"    {mod(t)} u_tile{t} (\n"
            f"        .wl(wl[{t*R} +: {R}]), .wbl(wbl), .drive(drive[{t*R*3} +: {R*3}]), .phi_rst(phi_rst),\n"
            f"        .phi_sh(phi_sh), .phi_mrg(phi_mrg), .phi_samp(phi_samp), .sar_clk(sar_clk),\n"
            f"        .codes(codes[{t*NC*B} +: {NC*B}]));" for t in range(N))
    if target == "beh":
        report = """
    integer fo;
    initial fo = $fopen({OUT}, "w");
    always @(posedge clk) if (rst_n && out_valid) begin
        $fwrite(fo, "%0d %0d %h %h\\n", out_m, out_nb, out_acc, out_y);
        if (out_acc !== ea_mem[nout] || out_y !== ey_mem[nout] || out_m !== em_mem[nout] || out_nb !== enb_mem[nout]) begin
            nbad = nbad + 1;
            if (nbad < 5) $display("MISMATCH out %0d: m %0d nb %0d acc %h exp %h y %h exp %h", nout, out_m, out_nb,
                                   out_acc, ea_mem[nout], out_y, ey_mem[nout]);
        end
        nout = nout + 1;
    end
    integer nsamp, s0;
    initial begin nsamp = 0; s0 = 0; end
    reg sar_q;
    initial sar_q = 0;
    always @(posedge clk) begin
        if (sar_clk && !sar_q) $fwrite(fo, "R %0d\\n", tick);
        sar_q <= sar_clk;
    end
    always @(posedge clk) if (phi_samp) begin
        $fwrite(fo, "S %0d\\n", tick);
        nsamp = nsamp + 1;
        if (nsamp == 1) s0 = stalls;
    end
    always @(posedge clk) if (job_done) begin
        $display("ticks=%0d passes=%0d stall_ticks=%0d stall_after_fill=%0d refreshes=%0d outputs=%0d/%0d mismatches=%0d",
                 tick, passes, stalls, stalls - s0, refreshes, nout, {NE}, nbad);
        $display("%s", (nbad == 0 && nout == {NE}) ? "PASS" : "FAIL");
        $fclose(fo);
        $finish;
    end
    initial begin #{TMAX}; $display("FAIL timeout ticks=%0d outputs=%0d", tick, nout); $finish; end
{TRACE}
"""
    else:
        # cosim: every output row, then the counters, leave as bytes on the obs channel
        pushes = "\n".join(f"            push(out_acc[{24*c+8*b+7}:{24*c+8*b}]);" for c in range(C) for b in range(3))
        pushes += "\n" + "\n".join(f"            push(out_y[{8*c+7}:{8*c}]);" for c in range(C))
        report = f"""
    always @(posedge clk) if (rst_n && out_valid) begin
            push(8'hA5); push(out_m[7:0]); push(out_nb[7:0]);
{pushes}
            nout = nout + 1;
    end
    reg sent;
    initial sent = 0;
    always @(posedge clk) if (job_done && !sent) begin
        sent = 1;
        push(8'h5A); push(stalls[7:0]); push(stalls[15:8]); push(passes[7:0]); push(passes[15:8]);
        push(tick[7:0]); push(tick[15:8]); push(tick[23:16]);
        fin = 1;
    end
"""
    tr = ""
    if trace:
        tr = """
    // pin trace (ns, hex): {sar_clk, phi_samp, phi_mrg, phi_sh, phi_rst, phi_drv, wbl, wl, drive}, LSB = drive[0]
    integer ft;
    reg [%d:0] pins_q;
    wire [%d:0] pins = {sar_clk, phi_samp, phi_mrg, phi_sh, phi_rst, phi_drv, wbl, wl, drive};
    initial begin ft = $fopen({TRF}, "w"); pins_q = 0; end
    always @(posedge clk or negedge clk) begin
        #0.001;
        if (pins !== pins_q) begin $fwrite(ft, "%%0.4f %%h\\n", $realtime, pins); pins_q = pins; end
    end
""" % (N * R * 3 + N * R + C * 8 + 5, N * R * 3 + N * R + C * 8 + 5)
    report = report.replace("{TRACE}", tr)
    report = report.replace("{NE}", str(ne)).replace("{TMAX}", str(4000 * 1000 + 300 * nx * 1000))
    return f"""
    // ---- job: M={L['M']} K={L['Kp']} N={L['Np']} (G={L['G']} k-groups, NB={L['NB']} n-blocks)
    reg [{R*8-1}:0]  x_mem  [0:{nx-1}];
    reg [{C*8-1}:0]  w_mem  [0:{nw-1}];
    reg [{C*21-1}:0] rq_mem [0:{len(L['rq'])-1}];
    reg [{C*24-1}:0] ea_mem [0:{ne-1}];
    reg [{C*8-1}:0]  ey_mem [0:{ne-1}];
    integer          em_mem [0:{ne-1}];
    integer          enb_mem [0:{ne-1}];
    reg [15:0]       cg_mem [0:{max(len(cal), 1)-1}];
    reg [19:0]       co_mem [0:{max(len(cal), 1)-1}];
    initial begin
        {(chr(10) + '        ').join(init)}
    end

    wire [{N*R-1}:0] wl;
    wire [{C*8-1}:0] wbl;
    wire [{N*R*3-1}:0] drive;
    wire phi_drv, phi_rst, phi_sh, phi_mrg, phi_samp, sar_clk;
    wire [{N*NC*B-1}:0] codes;
    wire w_ready, out_valid, job_done;
    wire [{N*32-1}:0] x_addr;
    wire [15:0] rq_addr, out_m, out_nb;
    wire [{C*8-1}:0] out_y;
    wire [{C*24-1}:0] out_acc;
    wire [31:0] stalls, passes, refreshes;
    reg  [{N*R*8-1}:0] x_data;
    reg  w_valid, start, cal_we;
    reg  [{C*8-1}:0] w_data;
    reg  [15:0] cal_addr, cal_g;
    reg  [19:0] cal_o;
    integer wp, hcnt, ci, nout, nbad, tick, t;
    always @* for (t = 0; t < {N}; t = t + 1) x_data[t*{R*8} +: {R*8}] = x_mem[x_addr[t*32 +: 32] % {nx}];

    // HBM model: first row after hbm_lat ticks, then one row per hbm_gap ticks, in use order
    initial begin wp = 0; hcnt = {cfg.hbm_lat}; w_valid = 0; w_data = 0; start = 0; cal_we = 0; ci = 0;
                  nout = 0; nbad = 0; tick = 0; cal_addr = 0; cal_g = 0; cal_o = 0; end
    always @(posedge clk) if (rst_n) begin
        tick <= tick + 1;
        if (ci < {len(cal)}) begin cal_we <= 1; cal_addr <= ci; cal_g <= cg_mem[ci]; cal_o <= co_mem[ci]; ci <= ci + 1; end
        else begin cal_we <= 0; start <= 1; end
        if (start) begin
            if (hcnt != 0) hcnt <= hcnt - 1;
            if (w_valid && w_ready) begin
                wp <= wp + 1;
                if ({cfg.hbm_gap} <= 1 && wp + 1 < {nw}) w_data <= w_mem[wp + 1]; else w_valid <= 0;
                hcnt <= {cfg.hbm_gap} - 1;
            end else if (!w_valid && hcnt == 0 && wp < {nw}) begin w_valid <= 1; w_data <= w_mem[wp]; end
        end
    end

    imc_driver #({pv}) u_drv (
        .clk_i(clk), .rst_ni(rst_n), .start_i(start), .cfg_m_i(16'd{L['M']}), .cfg_g_i(16'd{L['G']}),
        .cfg_nb_i(16'd{L['NB']}), .w_valid_i(w_valid), .w_ready_o(w_ready), .w_data_i(w_data),
        .x_addr_o(x_addr), .x_data_i(x_data), .rq_addr_o(rq_addr), .rq_data_i(rq_mem[rq_addr]),
        .cal_we_i(cal_we), .cal_addr_i(cal_addr), .cal_g_i(cal_g), .cal_o_i(cal_o),
        .wl_o(wl), .wbl_o(wbl), .drive_o(drive), .phi_drv_o(phi_drv), .phi_rst_o(phi_rst), .phi_sh_o(phi_sh),
        .phi_mrg_o(phi_mrg), .phi_samp_o(phi_samp), .sar_clk_o(sar_clk), .codes_i(codes),
        .out_valid_o(out_valid), .out_m_o(out_m), .out_nb_o(out_nb), .out_y_o(out_y),
        .out_acc_o(out_acc), .done_o(job_done), .stall_ticks_o(stalls), .passes_o(passes),
        .refreshes_o(refreshes));
{tiles}
{report}
"""


def tb_verilog(cfg, L, out_txt, cal=None, replay=None, trace_txt=None):
    b = body(cfg, L, "beh", cal, replay=replay, trace=trace_txt is not None)
    b = b.replace("{OUT}", f'"{out_txt}"').replace("{TRF}", f'"{trace_txt}"')
    return f"""`timescale 1ns/1ps
module tb;
    reg clk, rst_n;
    initial begin clk = 0; rst_n = 0; #1 rst_n = 1; end
    always #{HALF_PS / 1000} clk = ~clk;
{b}
endmodule
"""


def parse_trace(path, cfg):
    """(outputs [(m, nb, acc[C], y[C])], sample ticks) from the tb's output file."""
    C = cfg.cols
    outs, samp = [], []
    for line in Path(path).read_text().split("\n"):
        f = line.split()
        if not f:
            continue
        if f[0] == "S":
            samp.append(int(f[1]))
            continue
        if f[0] == "R":
            continue
        a, y = int(f[2], 16), int(f[3], 16)
        acc = [((a >> (24 * c)) & 0xFFFFFF) - (1 << 24) * (((a >> (24 * c)) >> 23) & 1) for c in range(C)]
        yy = [((y >> (8 * c)) & 0xFF) - 256 * (((y >> (8 * c)) >> 7) & 1) for c in range(C)]
        outs.append((int(f[0]), int(f[1]), acc, yy))
    return outs, samp

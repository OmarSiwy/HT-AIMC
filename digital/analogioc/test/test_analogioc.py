"""cocotb tests of analogioc_top + the analogioc behavioural model (INTERFACE.md §11).

Run: cd digital/analogioc/build/verification && make   (inside ./env.sh digital)

Every expected value comes from scripts/golden/model.py through
analog/analogioc/test/pass_vectors.py; every check is exact (the beh model is bit-true).
  A0   port views agree with analogioc.ports
  A11  weight write over wt_* then readback by MAC, all 272 cells x 6 patterns (96 passes),
       plus the beh assertions on an unwritten row and on a WL inside the window
  A7   the 11 real compiler passes back to back, JITTER 0 and 0.5 (3 seeds) (= A12 beh:
       a different weight set per pass, each written during the previous LO conversion),
       and a relu fixture vs golden.tile_mvm(relu=True)
  A8   one streamed cap changed by 1 LSB on pass_04_chk_max raises res_abft_flag
  E2E  attn_o column tiles accumulated over all 4 row tiles (cfg_tile_cnt = 4) from
       programming/attn_o.npz + acts: acc, residual and requantized output vs golden
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.handle import Force, Release
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "analog/analogioc/test"))
from golden import model as G  # noqa: E402
import pass_vectors as PV  # noqa: E402

OUT = Path(os.environ.get("COMPILER_OUT", ROOT / "scripts/compiler/out"))
PASSES = sorted((OUT / "passes").glob("pass_*"))
T_CLK = 20  # ns, LibreLane CLOCK_PERIOD = T_CLK_MAX


def need_compiler_out():
    assert PASSES, f"no compiler passes in {OUT}: run python3 scripts/compiler/compile.py"


# --------------------------------------------------------------------------- packing
def pack(vals, width):
    return sum((int(v) & ((1 << width) - 1)) << (width * k) for k, v in enumerate(vals))


def unpack(handle, width, n):
    v = int(handle.value)
    out = []
    for k in range(n):
        f = (v >> (width * k)) & ((1 << width) - 1)
        out.append(f - (1 << width) if f >> (width - 1) else f)
    return out


def signed(handle, width):
    return unpack(handle, width, 1)[0]


# --------------------------------------------------------------------------- bench
class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.codes, self.results, self.exposed = [], [], []
        self.wl_errors = 0
        self._stall = 0

    async def start(self, jitter=0.0, seed=1):
        d = self.dut
        cocotb.start_soon(Clock(d.clk, T_CLK, unit="ns").start())
        for s in ("pass_valid", "lw_valid", "wt_valid", "cfg_relu_en", "cfg_lora_en",
                  "lw_b", "lw_idx", "lw_code", "pass_x", "pass_abft_corr", "wt_data"):
            getattr(d, s).value = 0
        d.res_ready.value = 1
        d.rst_n.value = 0
        for _ in range(3):
            await RisingEdge(d.clk)
        d.u_analogioc.jitter.value = float(jitter)
        d.u_analogioc.seed.value = seed
        d.rst_n.value = 1
        await RisingEdge(d.clk)
        self.err0 = int(d.u_analogioc.n_prot_err.value)
        cocotb.start_soon(self.monitor())

    def prot_errors(self):
        return int(self.dut.u_analogioc.n_prot_err.value) - self.err0

    def config(self, D, s=(1,) * 16, budget=0xFFFF, rq=None, relu=0, tile_cnt=1):
        d = self.dut
        rq = rq or {"scale": [1] * 16, "shift": [0] * 16, "offset": [0] * 16}
        d.cfg_pkt_d.value = D
        d.cfg_tile_cnt.value = tile_cnt
        d.cfg_abft_s.value = pack([1 if v < 0 else 0 for v in s], 1)
        d.cfg_abft_budget.value = budget
        d.cfg_rq_scale.value = pack(rq["scale"], 8)
        d.cfg_rq_shift.value = pack(rq["shift"], 5)
        d.cfg_rq_offset.value = pack(rq["offset"], 8)
        d.cfg_relu_en.value = relu

    async def monitor(self):
        """Per clock: collect code/res outputs; check the §7.4 WL rules; count the
        cycles the HI start waits on the weight write (exposed write time)."""
        d = self.dut
        while True:
            await RisingEdge(d.clk)
            if int(d.rst_n.value) == 0:
                continue
            wl = int(d.w_wl_q.value)
            if wl and (wl & (wl - 1) or int(d.tile_busy.value) or int(d.integ_req_q.value)
                       or int(d.fsm_req.value)):
                self.wl_errors += 1
            if int(d.st.value) == 1 and int(d.all_rdy.value) and not int(d.w_loaded.value):
                self._stall += 1
            if int(d.code_valid.value):
                self.codes.append((unpack(d.code_hi, 8, 17), unpack(d.code_lo, 8, 17)))
                self.exposed.append(self._stall)
                self._stall = 0
            if int(d.res_valid.value) and int(d.res_ready.value):
                self.results.append({
                    "acc": unpack(d.res_acc, 20, 17), "q": unpack(d.res_q, 8, 16),
                    "residual": signed(d.res_residual, 25), "flag": int(d.res_abft_flag.value)})

    async def stream_weights(self, sets):
        d = self.dut
        for words in sets:
            for w in words:
                d.wt_data.value = w
                d.wt_valid.value = 1
                while True:
                    await RisingEdge(d.clk)
                    if int(d.wt_ready.value):
                        break
        d.wt_valid.value = 0

    async def send_passes(self, xs, corrs, cfgs=None):
        """One pass per item. cfg_* change only while idle: wait for idle, apply the
        pass's config with pass_valid, and the pass is accepted on the next edge."""
        d = self.dut
        for k, (x, c) in enumerate(zip(xs, corrs)):
            while True:
                await RisingEdge(d.clk)
                if int(d.pass_ready.value):
                    break
            if cfgs:
                self.config(**cfgs[k])
            d.pass_x.value = pack(x, 8)
            d.pass_abft_corr.value = int(c) & 0xFFFF
            d.pass_valid.value = 1
            await RisingEdge(d.clk)
            d.pass_valid.value = 0

    async def run(self, sets, xs, corrs, n_results, cfgs=None, max_us=4000):
        """Stream weight sets and passes concurrently, wait for n_results res beats."""
        self.codes, self.results, self.exposed = [], [], []
        cocotb.start_soon(self.stream_weights(sets))
        cocotb.start_soon(self.send_passes(xs, corrs, cfgs))
        for _ in range(max_us * 1000 // T_CLK):
            await RisingEdge(self.dut.clk)
            if len(self.results) >= n_results and len(self.codes) >= len(xs):
                return
        raise AssertionError(f"timeout: {len(self.codes)} codes, {len(self.results)} results")


def check_pass(v, code, res, tag):
    ex = v["expected"]
    hi, lo = code
    assert hi == ex["code_hi"], f"{tag}: code_hi {hi} != {ex['code_hi']}"
    assert lo == ex["code_lo"], f"{tag}: code_lo {lo} != {ex['code_lo']}"
    assert res["acc"][:16] == ex["y12"], f"{tag}: acc {res['acc'][:16]} != y12 {ex['y12']}"
    assert res["acc"][16] == ex["y12_chk"], f"{tag}: acc_chk {res['acc'][16]} != {ex['y12_chk']}"
    if not v["relu"]:
        assert res["residual"] == ex["residual"], f"{tag}: residual {res['residual']} != {ex['residual']}"
        assert res["flag"] == ex["flag"], f"{tag}: flag {res['flag']} != {ex['flag']}"
    assert res["q"] == ex["q"], f"{tag}: q {res['q']} != {ex['q']}"


# --------------------------------------------------------------------------- A0
@cocotb.test()
async def test_a0_ports(dut):
    """A0: macros.py check, and the .subckt pin order equals analogioc.ports."""
    r = subprocess.run([sys.executable, str(ROOT / "digital/analogioc/build/macros.py"), "check",
                        str(ROOT / "digital/analogioc/build/macros.toml")],
                       capture_output=True, text=True)
    assert "ports agree (37 signal ports, 5 supply pins)" in r.stdout, r.stdout + r.stderr
    ports = [l.split()[0] for l in (ROOT / "analog/analogioc/netlist/analogioc.ports").read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    deck = (ROOT / "analog/analogioc/netlist/analogioc.spice").read_text().replace("\n+", " ")
    sub = next(l for l in deck.splitlines() if l.lower().startswith(".subckt analogioc")).split()[2:]
    assert [p.replace("<", "[").replace(">", "]") for p in sub] == ports
    dut._log.info("A0 PASS: 37 signal ports, 5 supply pins, .subckt order == analogioc.ports")


# --------------------------------------------------------------------------- A11
@cocotb.test()
async def test_a11_unwritten_row_asserts(dut):
    """A11 (beh assertion): integ_req with never-written storage fires. Runs first,
    while the beh storage is still all x."""
    b = Bench(dut)
    await b.start()
    b.config(D=1)
    dut.w_loaded.value = Force(1)          # bypass the loader: HI starts unwritten
    cocotb.start_soon(b.send_passes([[0] * 16], [0]))
    for _ in range(200):
        await RisingEdge(dut.clk)
        if b.prot_errors():
            break
    dut.w_loaded.value = Release()
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    assert b.prot_errors() >= 1, "unwritten-storage assertion did not fire"
    dut._log.info("A11 unwritten-row assertion PASS")


def a11_sets(rng):
    """6 patterns per cell (v,0)/(0,v)/(v,v), then with 15-v: (Cp, Cn) as [j][i], 17 cols."""
    v = rng.integers(0, 16, size=(17, 16))
    out = []
    for vv in (v, 15 - v):
        z = np.zeros_like(vv)
        out += [(vv, z), (z, vv), (vv, vv)]
    return out


@cocotb.test()
async def test_a11_weight_write_readback(dut):
    """A11 beh: every cell written through wt_*, read back by MAC: one pass per row i
    with xq = 7 on row i (LO nibble 7, HI 0), D = 1 -> code_lo_j = 7 W[j][i] exactly."""
    b = Bench(dut)
    await b.start()
    b.config(D=1)
    pats = a11_sets(np.random.default_rng(11))
    sets, xs = [], []
    for Cp, Cn in pats:
        words = PV.row_words(Cp[:16], Cn[:16], [0] * 16)
        # column 16 carries its own pattern (not a chk split)
        words = [(w & ((1 << 128) - 1)) | ((int(Cp[16][i]) | int(Cn[16][i]) << 4) << 128)
                 for i, w in enumerate(words)]
        for i in range(16):                     # one set per pass: the same set 16 times
            sets.append(words)
            xs.append([7 if k == i else 0 for k in range(16)])
    await b.run(sets, xs, [0] * len(xs), n_results=len(xs))
    n = 0
    for p, (Cp, Cn) in enumerate(pats):
        W = Cp.astype(int) - Cn.astype(int)
        for i in range(16):
            hi, lo = b.codes[16 * p + i]
            want = [int(c) for c in G.eventrate_convert(7 * W[:, i], 1)["code"]]
            assert want == [7 * int(w) for w in W[:, i]]
            assert hi == [0] * 17, f"pattern {p} row {i}: code_hi {hi}"
            assert lo == want, f"pattern {p} row {i}: code_lo {lo} != {want}"
            n += 17
    assert b.prot_errors() == 0, f"{b.prot_errors()} protocol assertions"
    assert b.wl_errors == 0
    dut._log.info(f"A11 PASS: {len(xs)} passes, {n} cell reads exact (272 cells x 6 patterns), "
                  f"(v,v) reads 0, zero assertions")


@cocotb.test()
async def test_a11_wl_in_window_asserts(dut):
    """A11 (beh assertion): a word line raised inside the integrate window fires."""
    b = Bench(dut)
    await b.start()
    b.config(D=1)
    words = PV.row_words(np.ones((16, 16), int), np.zeros((16, 16), int), [0] * 16)
    cocotb.start_soon(b.stream_weights([words]))
    cocotb.start_soon(b.send_passes([[5] * 16], [0]))
    for _ in range(2000):
        await RisingEdge(dut.clk)
        if int(dut.u_analogioc.in_window.value):
            break
    assert b.prot_errors() == 0
    dut.w_wl_q.value = Force(1 << 3)
    for _ in range(2):
        await RisingEdge(dut.clk)
    dut.w_wl_q.value = Release()
    await RisingEdge(dut.clk)
    errs = b.prot_errors()
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    assert errs >= 1, "WL-during-window assertion did not fire"
    dut._log.info("A11 WL-in-window assertion PASS")


# --------------------------------------------------------------------------- A7 / A12
def real_vectors(relu=False):
    need_compiler_out()
    dig = json.loads((OUT / "digital_config.json").read_text())
    return [PV.pass_vectors(p, dig, relu=relu) for p in PASSES]


async def run_vectors(b, vecs, tag):
    """All passes in ONE back-to-back stream: weight sets stream ahead on wt_*, each
    pass's config is applied in the idle cycle before it is accepted."""
    cfgs = [dict(D=v["D"], s=v["s"], budget=v["budget"], rq=v["requant"], relu=v["relu"]) for v in vecs]
    b.config(**cfgs[0])
    await b.run([v["weights"] for v in vecs], [v["xq"] for v in vecs],
                [v["expected"]["corr"] for v in vecs], n_results=len(vecs), cfgs=cfgs)
    for v, code, res in zip(vecs, b.codes, b.results):
        check_pass(v, code, res, f"{tag} {v['tag']}")
    return b.exposed


@cocotb.test()
async def test_a7_a12_real_passes(dut):
    """A7/A12 beh: the 11 compiler passes, each with its own weight set streamed on wt_*
    during the previous pass's LO conversion; JITTER 0, then 0.5 with seeds 1..3."""
    vecs = real_vectors()
    for jitter, seed in ((0.0, 1), (0.5, 1), (0.5, 2), (0.5, 3)):
        b = Bench(dut)
        await b.start(jitter, seed)
        exposed = await run_vectors(b, vecs, f"J={jitter} seed={seed}")
        assert b.prot_errors() == 0, f"{b.prot_errors()} protocol assertions"
        assert b.wl_errors == 0
        dut.rst_n.value = 0
        await RisingEdge(dut.clk)
        dut._log.info(f"A7/A12 PASS J={jitter} seed={seed}: {len(vecs)} passes exact "
                      f"(code_hi/lo 17 cols, acc, residual, flag, q); exposed write per pass "
                      f"[ns] {[e * T_CLK for e in exposed]}")


@cocotb.test()
async def test_a7_relu_fixture(dut):
    """A7 relu fixture: cfg_relu_en = 1 on real passes vs golden.tile_mvm(relu=True)."""
    vecs = real_vectors(relu=True)
    n = np.zeros(3, int)                  # HI sign exits, LO forced to 0 after a HI exit, LO exits
    for v in vecs:
        t = G.tile_mvm_caps(np.array(v["Cp"]), np.array(v["Cn"]), np.array(v["xq"]), v["D"], relu=True)
        ex, ml = t["exit_hi"], t["mac_lo"]
        n += [ex.sum(), (ex & (ml > 0)).sum(), (~ex & (t["conv_hi"]["code"] == 0) & (ml < 0)).sum()]
    b = Bench(dut)
    await b.start()
    await run_vectors(b, vecs, "relu")
    assert b.prot_errors() == 0
    assert n.all(), f"fixture misses a relu path: {n}"
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut._log.info(f"A7 relu PASS: {len(vecs)} passes exact vs golden.tile_mvm(relu=True): {n[0]} HI sign "
                  f"exits, {n[1]} LO codes forced 0 after a HI exit, {n[2]} LO sign exits")


# --------------------------------------------------------------------------- A8
@cocotb.test()
async def test_a8_audit(dut):
    """A8 beh: pass_04_chk_max clean -> flag 0; one streamed cap +-1 LSB -> flag 1."""
    need_compiler_out()
    dig = json.loads((OUT / "digital_config.json").read_text())
    v = PV.pass_vectors(next(p for p in PASSES if p.name.endswith("chk_max")), dig)
    Cp, Cn = np.array(v["Cp"]), np.array(v["Cn"])
    xq = np.array(v["xq"])
    chk = np.array(v["chk"])
    # Every single-LSB fault of the row word, data columns first; golden decides which flag.
    # A data-column fault moves the residual by |x_i| <= 127 at most (17 here), so on this
    # pass (clean 127, budget 199) only the checksum column (x8) can reach the budget.
    faults = []
    for j in range(17):
        for i in range(16):
            for d in (1, -1):
                cp, cn, ck = Cp.copy(), Cn.copy(), chk.copy()
                if j < 16:
                    (cp if d > 0 else cn)[j, i] += 1      # +1 LSB on C+ or on C-
                    if cp[j, i] > 15 or cn[j, i] > 15:
                        continue
                else:
                    ck[i] += d
                    if abs(ck[i]) > 15:
                        continue
                ex = PV.expect(cp, cn, ck, v["chk_e"], v["s"], xq, v["D"], v["budget"], v["requant"])
                faults.append((j < 16 and ex["flag"], ex["flag"], abs(ex["residual"]), (j, i, d), ex, cp, cn, ck))
    faults.sort(key=lambda f: f[:3], reverse=True)
    n_data = sum(1 for f in faults if f[0])
    assert faults[0][1], "no single-LSB fault exceeds the budget on this pass"
    _, _, _, (j, i, dp), ex_f, cp, cn, ck = faults[0]
    faulty = dict(v, weights=PV.row_words(cp, cn, ck), expected=ex_f, tag="fault")
    b = Bench(dut)
    await b.start()
    await run_vectors(b, [dict(v, tag="clean"), faulty], "A8")
    assert b.results[0]["flag"] == 0 and b.results[1]["flag"] == 1
    assert b.prot_errors() == 0
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut._log.info(f"A8 PASS: clean residual {v['expected']['residual']} flag 0; cell (col {j}, row {i}) "
                  f"W{dp:+d} -> residual {ex_f['residual']} > budget {v['budget']}, flag 1 "
                  f"({n_data} of {len(faults)} single-LSB faults on data columns flag on this pass)")


# --------------------------------------------------------------------------- E2E accumulate
@cocotb.test()
async def test_e2e_attn_o_accumulate(dut):
    """Whole outputs: attn_o (576 x 64, 4 row tiles) column tiles from programming/attn_o.npz,
    last token's activations; cfg_tile_cnt = 4, so acc / residual / q are the real
    layer outputs (golden mvm_layer + requant_int8 = golden.proj)."""
    need_compiler_out()
    npz = np.load(OUT / "programming/attn_o.npz")
    xq = np.load(OUT / "acts/attn_o.npz")["xq"][-1]
    D, s16 = int(npz["D"]), npz["s16"]
    dig = json.loads((OUT / "digital_config.json").read_text())
    budget = dig["matrices"]["attn_o"]["abft"]["budget"]
    acc_g, _, _ = G.mvm_layer(npz["Wq"], xq, D)
    out8 = G.requant_int8(acc_g, npz["scale"], npz["shift"], npz["offset"])
    n_ct = int(os.environ.get("E2E_COL_TILES", npz["Cp"].shape[0] // 16))   # all 36 by default
    b = Bench(dut)
    await b.start()
    for c in range(n_ct):
        rq = PV.requant_fields(dig, "attn_o", c)
        b.config(D=D, s=s16, budget=budget, rq=rq, tile_cnt=4)
        sets, xs, corrs, resid = [], [], [], 0
        for r in range(4):
            Cp, Cn, chk, e = PV.matrix_tile(npz, c, r)
            xt = xq[r * 16:(r + 1) * 16]
            ex = PV.expect(Cp, Cn, chk, e, s16, xt, D, budget, rq)
            sets.append(PV.row_words(Cp, Cn, chk))
            xs.append(xt)
            corrs.append(ex["corr"])
            resid += ex["residual"]
        await b.run(sets, xs, corrs, n_results=1)
        res = b.results[0]
        js = slice(c * 16, c * 16 + 16)
        assert res["acc"][:16] == [int(a) for a in acc_g[js]], f"ct {c}: acc"
        assert res["residual"] == resid, f"ct {c}: residual {res['residual']} != {resid}"
        assert res["flag"] == int(abs(resid) > budget)
        assert res["q"] == [int(q) for q in out8[js]], f"ct {c}: q {res['q']} != {list(out8[js])}"
    assert b.prot_errors() == 0
    dut._log.info(f"E2E PASS: attn_o column tiles 0..{n_ct - 1} x 4 row tiles ({4 * n_ct} passes): "
                  f"acc, residual, q == golden proj exactly")

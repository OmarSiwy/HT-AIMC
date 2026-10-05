"""Host scheduler + numpy golden for sa_top (weight-stationary systolic array).

The scheduler is the "minimal control" of the reference: it turns a list of INT8
GEMMs into a cycle-exact stream on sa_top's three ports, obeying the RTL contract
(sa_top.sv header). The same function, run without data, is the utilization model
used for the PPA numbers, and the RTL simulation checks its cycle count.

Tile loop per GEMM y = requant(X @ W):  for n-tile: for m-chunk: for k-tile.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from golden.model import requant_int8  # noqa: E402  (repo's bit-exact requant)


def golden(X, W, scale, shift, offset):
    """INT8 GEMM -> INT32 acc -> requant. X (M,K), W (K,N) ints. Returns (acc, y8)."""
    acc = X.astype(np.int64) @ W.astype(np.int64)
    assert np.all(np.abs(acc) < 2**31), "INT32 accumulator range"
    return acc, requant_int8(acc, scale, shift, offset)


class Cfg:
    def __init__(self, rows=16, cols=16, ww=8, acc_depth=16, pipe=1):
        self.R, self.C, self.WW, self.D, self.P = rows, cols, ww, acc_depth, pipe
        self.row_w = max(1, (rows - 1).bit_length())
        self.idx_w = max(1, (acc_depth - 1).bit_length())
        # issue -> y_valid_o of the last column (see sa_top tag alignment + 3 edge stages)
        self.lat = 1 + rows + pipe + (cols - 1) + 3


def schedule(cfg, jobs, data=True):
    """jobs: list of dict(X, W, scale, shift, offset) (or dict(M,K,N) if not data).

    Returns (events, n_cycles, outputs, macs) where events[t] is a dict of port
    values at cycle t, outputs the expected (idx, y_row) list in emission order and
    macs the useful MAC count (unpadded).
    """
    R, C, D = cfg.R, cfg.C, cfg.D
    ev = {}
    outs, sums = [], []

    def at(t):
        return ev.setdefault(t, {})

    wbus_free = act_free = rq_free = 0
    last_issue = [-10**9, -10**9]          # per weight bank
    group_last = []                        # last issue cycle per output group
    tile_i = group_i = 0
    macs = 0
    for job in jobs:
        if data:
            X, W = job["X"], job["W"]
            M, K = X.shape
            N = W.shape[1]
        else:
            M, K, N = job["M"], job["K"], job["N"]
        macs += M * K * N
        Kp, Np = -(-K // R) * R, -(-N // C) * C
        if data:
            Xp = np.zeros((M, Kp), np.int64); Xp[:, :K] = X
            Wp = np.zeros((Kp, Np), np.int64); Wp[:K, :N] = W
            sc = np.zeros(Np, np.int64); sc[:N] = job["scale"]
            sh = np.zeros(Np, np.int64); sh[:N] = job["shift"]
            of = np.zeros(Np, np.int64); of[:N] = job["offset"]
            acc, y8 = golden(Xp, Wp, sc, sh, of)
        nk = Kp // R
        for n0 in range(0, Np, C):
            for m0 in range(0, M, D):
                mc = min(D, M - m0)
                g, gb = group_i, group_i % 2
                # requant bank gb is free once group g-2 has fully drained
                q = rq_free
                if g >= 2:
                    q = max(q, group_last[g - 2] + cfg.lat + 1)
                if data:
                    at(q)["rq"] = (gb, sc[n0:n0 + C], sh[n0:n0 + C], of[n0:n0 + C])
                rq_free = q + 1
                for kt in range(nk):
                    b = tile_i % 2
                    L = max(wbus_free, last_issue[b] + C - 1)
                    if data:
                        for r in range(R):
                            at(L + r)["w"] = (r, b, Wp[kt * R + r, n0:n0 + C])
                    wbus_free = L + R
                    S = max(act_free, L + 1, q + 1)
                    for m in range(mc):
                        e = at(S + m)
                        e["a"] = (b, kt == 0, kt == nk - 1, gb, m,
                                  Xp[m0 + m, kt * R:(kt + 1) * R] if data else None)
                    act_free = S + mc
                    last_issue[b] = S + mc - 1
                    tile_i += 1
                group_last.append(last_issue[(tile_i - 1) % 2])
                if data:
                    for m in range(mc):
                        outs.append((m, y8[m0 + m, n0:n0 + C]))
                        sums.append(acc[m0 + m, n0:n0 + C])
                group_i += 1
    n_cyc = max(ev) + 1 if ev else act_free
    return ev, n_cyc, outs, sums, macs, act_free


def pack(cfg, ev, n_cyc):
    """Pack events into the tb_sa_top stimulus words (LSB-first field order)."""
    R, C, WW = cfg.R, cfg.C, cfg.WW
    wmask = (1 << WW) - 1
    words = []
    for t in range(n_cyc):
        e = ev.get(t, {})
        fields = []                         # (value, width), LSB first
        if "w" in e:
            r, b, wrow = e["w"]
            wd = sum((int(v) & wmask) << (WW * i) for i, v in enumerate(wrow))
            fields += [(1, 1), (r, cfg.row_w), (b, 1), (wd, C * WW)]
        else:
            fields += [(0, 1), (0, cfg.row_w), (0, 1), (0, C * WW)]
        if "a" in e:
            b, first, last, rqsel, idx, avec = e["a"]
            ad = sum((int(v) & 0xFF) << (8 * i) for i, v in enumerate(avec))
            fields += [(1, 1), (ad, R * 8), (b, 1), (int(first), 1), (int(last), 1),
                       (rqsel, 1), (idx, cfg.idx_w)]
        else:
            fields += [(0, 1), (0, R * 8), (0, 4), (0, cfg.idx_w)]
        if "rq" in e:
            gb, sc, sh, of = e["rq"]
            fields += [(1, 1), (gb, 1),
                       (sum(int(v) << (8 * i) for i, v in enumerate(sc)), C * 8),
                       (sum(int(v) << (5 * i) for i, v in enumerate(sh)), C * 5),
                       (sum((int(v) & 0xFF) << (8 * i) for i, v in enumerate(of)), C * 8)]
        else:
            fields += [(0, 2 + C * 21)]
        word, pos = 0, 0
        for v, w in fields:
            word |= (v & ((1 << w) - 1)) << pos
            pos += w
        words.append(word)
    return words


def utilization(cfg, M, K, N):
    """Steady-state MAC utilization of one GEMM (issue-bound, fill/drain excluded
    because back-to-back GEMMs overlap it): useful MACs / (cycles * R * C)."""
    *_, macs, issue_end = schedule(cfg, [dict(M=M, K=K, N=N)], data=False)
    return macs / (issue_end * cfg.R * cfg.C), issue_end

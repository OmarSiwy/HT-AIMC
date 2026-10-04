"""Minimal numpy-only GGUF reader (CONTRACT.md real-model mandate).

Parses header, metadata KV, tensor table; dequantizes F32/F16 passthrough,
Q8_0 (34B block: f16 scale + 32 int8, w = d*q) and Q4_0 fallback (18B block:
f16 scale + 16B nibbles, w = d*(q-8)). Tensor arrays are returned with numpy
shape = reversed ggml ne, i.e. (out, in) row-major for 2-D weights.
"""

import struct
import numpy as np

GGUF_MAGIC = 0x46554747
_SCALAR = {0: ("<u1", 1), 1: ("<i1", 1), 2: ("<u2", 2), 3: ("<i2", 2),
           4: ("<u4", 4), 5: ("<i4", 4), 6: ("<f4", 4), 7: ("<u1", 1),
           10: ("<u8", 8), 11: ("<i8", 8), 12: ("<f8", 8)}
# ggml_type: (block_elems, block_bytes)
GGML_F32, GGML_F16, GGML_Q4_0, GGML_Q8_0 = 0, 1, 2, 8
GGML_Q4_K, GGML_Q5_K, GGML_Q6_K = 12, 13, 14
_BLOCK = {GGML_F32: (1, 4), GGML_F16: (1, 2), GGML_Q4_0: (32, 18), GGML_Q8_0: (32, 34),
          GGML_Q4_K: (256, 144), GGML_Q5_K: (256, 176), GGML_Q6_K: (256, 210)}


def _f16(b):
    """(N, 2) uint8 -> float32 scale column."""
    return b.copy().view("<f2").astype(np.float32).reshape(-1)


def _kscales(sb):
    """llama.cpp get_scale_min_k4: 12 packed bytes -> (8 scales, 8 mins),
    each 6-bit unsigned. Returns (N, 8), (N, 8) float32."""
    sb = sb.astype(np.uint8)
    sc = np.empty(sb.shape[:1] + (8,), dtype=np.float32)
    mn = np.empty_like(sc)
    for j in range(4):
        sc[:, j] = sb[:, j] & 63
        mn[:, j] = sb[:, j + 4] & 63
        sc[:, j + 4] = (sb[:, j + 8] & 15) | ((sb[:, j] >> 6) << 4)
        mn[:, j + 4] = (sb[:, j + 8] >> 4) | ((sb[:, j + 4] >> 6) << 4)
    return sc, mn


def _dequant_q4k(blk):
    """Q4_K: w = d*sc[sub]*q4 - dmin*min[sub]; sub-blocks of 32, chunk j of 64
    = (low nibbles -> sub 2j, high nibbles -> sub 2j+1) of qs[32j:32j+32]."""
    d, dmin = _f16(blk[:, 0:2]), _f16(blk[:, 2:4])
    sc, mn = _kscales(blk[:, 4:16])
    qs = blk[:, 16:144]
    v = np.empty((blk.shape[0], 256), dtype=np.float32)
    for j in range(4):
        v[:, 64 * j:64 * j + 32] = qs[:, 32 * j:32 * j + 32] & 15
        v[:, 64 * j + 32:64 * j + 64] = qs[:, 32 * j:32 * j + 32] >> 4
    v = v.reshape(-1, 8, 32)
    w = d[:, None, None] * sc[:, :, None] * v - dmin[:, None, None] * mn[:, :, None]
    return w.reshape(-1)


def _dequant_q5k(blk):
    """Q5_K: like Q4_K with a 5th bit from qh: chunk j low half uses qh bit
    2j, high half bit 2j+1 (per l in 0..31)."""
    d, dmin = _f16(blk[:, 0:2]), _f16(blk[:, 2:4])
    sc, mn = _kscales(blk[:, 4:16])
    qh, qs = blk[:, 16:48], blk[:, 48:176]
    v = np.empty((blk.shape[0], 256), dtype=np.float32)
    for j in range(4):
        v[:, 64 * j:64 * j + 32] = (qs[:, 32 * j:32 * j + 32] & 15) \
            + ((qh >> (2 * j)) & 1) * 16
        v[:, 64 * j + 32:64 * j + 64] = (qs[:, 32 * j:32 * j + 32] >> 4) \
            + ((qh >> (2 * j + 1)) & 1) * 16
    v = v.reshape(-1, 8, 32)
    w = d[:, None, None] * sc[:, :, None] * v - dmin[:, None, None] * mn[:, :, None]
    return w.reshape(-1)


def _dequant_q6k(blk):
    """Q6_K: two halves of 128; q = (ql nibble | qh 2-bit << 4) - 32, int8
    scale per 16 elems: w = d * scales[pos//16] * q."""
    N = blk.shape[0]
    ql = blk[:, 0:128].reshape(N, 2, 64)
    qh = blk[:, 128:192].reshape(N, 2, 32)
    sc = blk[:, 192:208].copy().view(np.int8).reshape(N, 2, 8).astype(np.float32)
    d = _f16(blk[:, 208:210])
    nib = np.concatenate([ql & 15, ql >> 4], axis=2)          # pos 0..127
    hi = np.concatenate([(qh >> k) & 3 for k in (0, 2, 4, 6)], axis=2)
    q = (nib | (hi << 4)).astype(np.float32) - 32.0
    w = d[:, None, None] * np.repeat(sc, 16, axis=2) * q
    return w.reshape(-1)


class GGUF:
    """gguf = GGUF(path); gguf.meta['llama.embedding_length']; gguf.array(name)."""

    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        magic, self.version = struct.unpack("<II", self.f.read(8))
        assert magic == GGUF_MAGIC, f"not a GGUF file: {path}"
        assert self.version in (2, 3), f"unsupported GGUF version {self.version}"
        n_tensors, n_kv = struct.unpack("<QQ", self.f.read(16))
        self.meta = {}
        for _ in range(n_kv):
            k = self._str()
            self.meta[k] = self._value(struct.unpack("<I", self.f.read(4))[0])
        self.tensors = {}
        for _ in range(n_tensors):
            name = self._str()
            nd = struct.unpack("<I", self.f.read(4))[0]
            ne = struct.unpack(f"<{nd}Q", self.f.read(8 * nd))
            ttype, off = struct.unpack("<IQ", self.f.read(12))
            self.tensors[name] = (ttype, ne, off)
        align = int(self.meta.get("general.alignment", 32))
        pos = self.f.tell()
        self.data_start = pos + (-pos % align)

    def _str(self):
        n = struct.unpack("<Q", self.f.read(8))[0]
        return self.f.read(n).decode("utf-8", errors="replace")

    def _value(self, t):
        if t == 8:
            return self._str()
        if t == 9:
            et, n = struct.unpack("<IQ", self.f.read(12))
            if et == 8:
                return [self._str() for _ in range(n)]
            if et == 9:
                return [self._value(9) for _ in range(n)]
            dt, sz = _SCALAR[et]
            v = np.frombuffer(self.f.read(sz * n), dtype=dt)
            return v.astype(bool).tolist() if et == 7 else v.tolist()
        dt, sz = _SCALAR[t]
        v = np.frombuffer(self.f.read(sz), dtype=dt)[0]
        return bool(v) if t == 7 else v.item()

    def array(self, name):
        """Dequantized float32 ndarray, shape = reversed ne (row-major, ne[0] fastest)."""
        ttype, ne, off = self.tensors[name]
        n = int(np.prod(ne))
        be, bb = _BLOCK[ttype]  # KeyError = unsupported quant type (add here)
        assert n % be == 0
        self.f.seek(self.data_start + off)
        raw = self.f.read((n // be) * bb)
        if ttype == GGML_F32:
            w = np.frombuffer(raw, dtype="<f4").astype(np.float32)
        elif ttype == GGML_F16:
            w = np.frombuffer(raw, dtype="<f2").astype(np.float32)
        elif ttype == GGML_Q8_0:
            blk = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 34)
            d = blk[:, :2].copy().view("<f2").astype(np.float32)
            q = blk[:, 2:].copy().view(np.int8).astype(np.float32)
            w = (d * q).reshape(-1)
        elif ttype == GGML_Q4_0:
            blk = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 18)
            d = blk[:, :2].copy().view("<f2").astype(np.float32)
            qs = blk[:, 2:]
            q = np.concatenate([qs & 15, qs >> 4], axis=1).astype(np.float32) - 8.0
            w = (d * q).reshape(-1)
        elif ttype == GGML_Q4_K:
            w = _dequant_q4k(np.frombuffer(raw, dtype=np.uint8).reshape(-1, 144))
        elif ttype == GGML_Q5_K:
            w = _dequant_q5k(np.frombuffer(raw, dtype=np.uint8).reshape(-1, 176))
        elif ttype == GGML_Q6_K:
            w = _dequant_q6k(np.frombuffer(raw, dtype=np.uint8).reshape(-1, 210))
        return w.reshape(tuple(reversed(ne)))


# ---------------------------------------------------------------------------
# byte-level BPE surface forms + greedy longest-match tokenizer
# ---------------------------------------------------------------------------

def _bytes_to_unicode():
    """GPT-2 byte encoder: maps each byte to the printable char used in the
    GGUF-embedded vocab strings ('Ġ' = space, 'Ċ' = newline, ...)."""
    bs = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


def tokenize_greedy(text, vocab):
    """Greedy longest-match over the GGUF-embedded vocab surface strings.

    FIDELITY CAVEAT (documented per mandate): this ignores BPE merge ranks;
    ids can differ from the reference tokenizer on rare strings. Adequate for
    driving real weights with a real prompt; not a tokenizer-parity claim.
    Returns list of token ids.
    """
    b2u = _bytes_to_unicode()
    s = "".join(b2u[b] for b in text.encode("utf-8"))
    index = {}
    for i, tok in enumerate(vocab):
        index.setdefault(tok, i)  # first (lowest) id wins on duplicates
    maxlen = max(len(t) for t in index)
    ids, pos = [], 0
    while pos < len(s):
        for ln in range(min(maxlen, len(s) - pos), 0, -1):
            tid = index.get(s[pos:pos + ln])
            if tid is not None:
                ids.append(tid)
                pos += ln
                break
        else:
            pos += 1  # unmatchable byte: skip (documented)
    return ids


# ---------------------------------------------------------------------------
# fixture blob for unit tests (spec-true tiny GGUF)
# ---------------------------------------------------------------------------

def write_fixture_gguf(path, tensors, meta=None):
    """Write a minimal GGUF v3 file: meta strings/ints/arrays + Q8_0/F32 tensors.

    tensors: dict name -> (np.float32 2-D array, 'q8_0'|'f32'). Q8_0 encode:
    per-32 block d = max|w|/127, q = rint(w/d) — reference round-trip for the
    reader test.
    """
    meta = dict(meta or {})
    out = bytearray()
    out += struct.pack("<IIQQ", GGUF_MAGIC, 3, len(tensors), len(meta))

    def s(x):
        b = x.encode()
        return struct.pack("<Q", len(b)) + b

    for k, v in meta.items():
        out += s(k)
        if isinstance(v, str):
            out += struct.pack("<I", 8) + s(v)
        elif isinstance(v, list):
            out += struct.pack("<II", 9, 8) + struct.pack("<Q", len(v))
            for e in v:
                out += s(e)
        else:
            out += struct.pack("<I", 4) + struct.pack("<I", int(v))

    blobs = []
    off = 0
    for name, (w, kind) in tensors.items():
        ne = tuple(reversed(w.shape))
        ttype = GGML_F32 if kind == "f32" else GGML_Q8_0
        flat = np.ascontiguousarray(w, dtype=np.float32).reshape(-1)
        if kind == "f32":
            blob = flat.astype("<f4").tobytes()
        else:
            assert flat.size % 32 == 0
            blk = flat.reshape(-1, 32)
            d = np.max(np.abs(blk), axis=1) / 127.0
            d[d == 0] = 1.0
            q = np.clip(np.rint(blk / d[:, None]), -127, 127).astype(np.int8)
            b = np.zeros((blk.shape[0], 34), dtype=np.uint8)
            b[:, :2] = d.astype("<f2")[:, None].view(np.uint8)
            b[:, 2:] = q.view(np.uint8)
            blob = b.tobytes()
        out += s(name) + struct.pack("<I", len(ne))
        out += struct.pack(f"<{len(ne)}Q", *ne)
        out += struct.pack("<IQ", ttype, off)
        blobs.append(blob)
        off += len(blob) + (-len(blob) % 32)
    out += b"\0" * (-len(out) % 32)
    for blob in blobs:
        out += blob + b"\0" * (-len(blob) % 32)
    with open(path, "wb") as f:
        f.write(out)

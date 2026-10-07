"""N5 array geometry & analog accuracy.

Default 128 rows (the measured sky130 passive macro height) x 64 logical columns,
one checksum column per weight slice (ABFT, METRICS.md), 8 columns per ADC.
Accuracy (projected screen, not a SPICE result):
  signal  sigma_sig = 2 V_exc rho / sqrt(R)   (differential charge share over R rows,
          rho = normalized rms of one x*w product; tune it from real operands)
  thermal kT/C on the column, both sides       (27g2: same law as an ADC)
  mismatch sigma_C/C = sigma_1fF / sqrt(Cu)     (static; 27d6 says training can absorb it)
  ADC     10 log10(12 4^B / 64)                (+-4 sigma full scale, imc_architecture_search)
"""
import math

from arch_eval import asap7 as k

OPTIONS = {
    "r128c64": dict(params=dict(rows=128, cols=64, adc_share=8, checksum=1, rho=0.1),
                    provenance="rows: measured sky130 macro; cols/share: projected"),
}
DEFAULT = "r128c64"
SWEEP = dict(rows=[64, 128, 256, 512], cols=[32, 64, 128], adc_share=[1, 4, 8, 16])


def geometry(p):
    return dict(rows=int(p["rows"]), cols=int(p["cols"]), adc_share=int(p["adc_share"]),
                checksum=int(p.get("checksum", 1)))


def _db(x):
    return 10 * math.log10(x)


def signal_rms(p, geo, arr):
    return 2 * arr["v_exc_V"] * p["rho"] / math.sqrt(geo["rows"])


def v_range(p, geo, arr):
    """Converter input range Vc = +-4 sigma of the column signal (V)."""
    return 8 * signal_rms(p, geo, arr)


def accuracy(p, vdd, geo, arr, adc, fmt):
    sig = signal_rms(p, geo, arr)
    noise_th = 2 * k.get("kT_300K_J") / (arr["c_col_fF"] * 1e-15)
    sc = k.get("cap_match_sigma_pct_at_1fF") / 100 / math.sqrt(p["cu_fF"])
    parts = dict(thermal=_db(sig ** 2 / noise_th), mismatch=_db(1 / sc ** 2),
                 adc=_db(12 * 4 ** adc["bits"] / 64))
    total = -_db(sum(10 ** (-v / 10) for v in parts.values()))
    return dict(snr_db=total, parts_db=parts, v_signal_rms_V=sig)

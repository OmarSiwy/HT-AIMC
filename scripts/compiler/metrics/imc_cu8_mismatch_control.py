"""Paid Cu8 control: same signed8/A11/ADC choices and paired physical draws."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics import imc_fixed_mismatch_quality as fixed
from compiler.metrics.imc_fixed_cap_mismatch import coefficient_variance
legacy, nominal, np = fixed.legacy, fixed.nominal, fixed.np
MEASURED = ROOT/'build/campaign/programmable_cap/w042_tt27_cu8_s8_step1_r1/result.json'
DIE = 1
OUT = ROOT/'build/campaign/cu8_mismatch_control/die1'
data = json.loads(MEASURED.read_text())
assert data['unit_fF'] == 8 and data['width_um'] == .42
CAPS = np.empty(16)
for row in data['rows']:
    c = row['port_loading'][0]
    assert c['frequency_Hz'] == 1000
    if row['mode'] == 'compiled':
        assert np.isclose(c['effective_cap_fF'], 8*row['code'], atol=1e-10)
    if row['mode'] == 'bypass':
        CAPS[row['code']] = c['effective_cap_fF']


def scenes(q, w, dx, pooled, fmt):
    assert not pooled
    banks = fixed.scenes(q, w, dx, pooled, fmt)
    for bank, digit in zip(banks, nominal.digits(w, fmt)[:2]):
        for g, scene in enumerate(bank):
            scene['units'] = CAPS[abs(digit[g*256:(g+1)*256])].sum(axis=0)[None, :]/8
    return banks


def freeze():
    p = json.loads((ROOT/f'build/campaign/fixed_mismatch_quality/die{DIE}/protocol.json').read_text())
    for f in (Path(__file__), MEASURED):
        p['sources'][str(f)] = legacy.base.fingerprint(f)
    p['Cu_fF'] = [8]
    p['formats'] = ['signed8']
    p['architectures'] = [a for a in p['architectures'] if a['label'] == 'common_A11_separate']
    p['status'] = 'Frozen Cu8 brute-force area baseline, before quality results'
    p['mismatch']['geometry'] = 'Square8/16/32/64fF TT PDK area law; same Gaussian physical draws as Cu4, changed sigma only'
    p['programming_model'] = dict(effective_C_fF_by_unsigned_code=CAPS.tolist(),
        source=str(MEASURED), frequency_Hz=1000,
        limitation='Unsigned TT AC loading only. Cu8 fixture fails dynamic charge gate at8ns; no timing/PVT or full-array pass. Ideal signal transfer, nominal holder matching and lumped kT/C remain conditional.')
    p['calibration'] = 'Byte-identical Cu4 ADC settings; no new depth/span/activation precision or mismatch correction. ADC charge step and physical capacitor allocation scale with Cu8.'
    p['cost'] = 'Cu doubles installed magnitude capacitors from88 to176fF/weight for minimal22-unit banks, or120 to240fF for two measured4bit fixtures. Matched holders/coarse caps and actual active loading counted separately. Additional settling time required but unmeasured here.'
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT/'protocol.json'; text = json.dumps(p, indent=2)+'\n'
    if path.exists(): assert path.read_text() == text
    else: path.write_text(text)
    src, dst = nominal.OUT/'calibration_Cu4.json', OUT/'calibration_Cu8.json'
    if dst.exists(): assert dst.read_bytes() == src.read_bytes()
    else: dst.write_bytes(src.read_bytes())
    return p


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--die', type=int, choices=(1, 2), default=1)
    ap.add_argument('--freeze', action='store_true')
    args = ap.parse_args(); DIE = args.die
    OUT = ROOT/f'build/campaign/cu8_mismatch_control/die{DIE}'
    fixed.DIE = DIE
    fixed.coefficient_variance = lambda codes: coefficient_variance(codes, unit=8)
    legacy.digits, legacy.radix = nominal.digits, nominal.radix
    legacy.OUT, legacy.prepare, legacy.scenes = OUT, nominal.reset.prepare, scenes
    legacy.selfcheck, legacy.freeze, legacy.load = fixed.selfcheck, freeze, fixed.load
    if args.freeze: freeze()
    else: legacy.evaluate(8)

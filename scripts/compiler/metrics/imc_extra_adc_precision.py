"""One additional ADC bit at half span: same range, paid finer quantum."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics import imc_cu8_mismatch_control as prior
fixed, nominal, legacy = prior.fixed, prior.nominal, prior.legacy
DIE = 1
OUT = ROOT/'build/campaign/extra_adc_precision/die1'


def freeze():
    old = ROOT/f'build/campaign/cu8_mismatch_control/die{DIE}'
    p = json.loads((old/'protocol.json').read_text())
    src = nominal.OUT/'calibration_Cu4.json'
    for f in (Path(__file__), Path(prior.__file__), src):
        p['sources'][str(f)] = legacy.base.fingerprint(f)
    p['status'] = 'Frozen paid +1 ADC bit and half span; no calibration or activation changes'
    p['modes'] = [['fixed_mismatch_only', 0, False, None]]+[
        ['fixed_mismatch_read20', 20, True, seed] for seed in range(60001, 60009)]
    p['calibration'] = 'Each original signed8 A11 separate ADC choice changes n to n+1 and span to span/2. Full charge range unchanged, quantum halved. No data refit.'
    p['cost'] = 'One extra comparator decision/conversion and doubled native coarse-CDAC host demand. Actual padding/holder caps are allocated by the existing engine. Halved reference-charge quantum requires physical reference/DAC precision and settling validation; no free fine-quantum credit.'
    p['ADC_bits'] = [11,12,13,14,15]
    p['robustness'] = 'Declared seeds60001..60008, both exposed passages and two existing fixed physical dies. Mismatch-only diagnostics also retained. No yield/unseen-corpus or timing pass.'
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT/'protocol.json'; text = json.dumps(p, indent=2)+'\n'
    if path.exists(): assert path.read_text() == text
    else: path.write_text(text)
    cal = json.loads(src.read_text())
    records = []
    for row in cal['records']:
        if row['format']=='signed8' and row['architecture']=='common_A11_separate':
            original = row['selected']['min_error']
            records.append({k:row[k] for k in ('format','architecture','layer','tensor','bank')}|
                           dict(selected={'min_error':dict(bits=original['bits']+1,span=original['span']/2)}))
    assert len(records)==420
    cal['records'] = records; cal['Cu_fF'] = 8; cal['protocol'] = p
    cal['sources'][str(src)] = legacy.base.fingerprint(src)
    cal['override'] = p['calibration']
    path = OUT/'calibration_Cu8.json'; text = json.dumps(cal, indent=2)+'\n'
    if path.exists(): assert path.read_text() == text
    else: path.write_text(text)
    return p


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--die', type=int, choices=(1, 2), default=1)
    ap.add_argument('--freeze', action='store_true')
    args = ap.parse_args(); DIE = args.die
    OUT = ROOT/f'build/campaign/extra_adc_precision/die{DIE}'
    fixed.DIE = DIE
    fixed.coefficient_variance = lambda codes: prior.coefficient_variance(codes, unit=8)
    legacy.digits, legacy.radix = nominal.digits, nominal.radix
    legacy.OUT, legacy.prepare, legacy.scenes = OUT, nominal.reset.prepare, prior.scenes
    legacy.selfcheck, legacy.freeze, legacy.load = fixed.selfcheck, freeze, fixed.load
    if args.freeze: freeze()
    else: legacy.evaluate(8)

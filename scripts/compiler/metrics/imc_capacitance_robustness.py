"""Frozen Cu6 midpoint control and eight-seed Cu8 robustness extension."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics import imc_cu8_mismatch_control as prior
fixed, nominal, legacy, np = prior.fixed, prior.nominal, prior.legacy, prior.np
DIE, CU = 1, 8
OUT = ROOT/'build/campaign/capacitance_robustness/Cu8/die1'
CAPS = prior.CAPS.copy()


def scenes(q, w, dx, pooled, fmt):
    assert not pooled
    banks = fixed.scenes(q, w, dx, pooled, fmt)
    for bank, digit in zip(banks, nominal.digits(w, fmt)[:2]):
        for g, scene in enumerate(bank):
            scene['units'] = CAPS[abs(digit[g*256:(g+1)*256])].sum(axis=0)[None, :]/CU
    return banks


def freeze():
    old = ROOT/f'build/campaign/cu8_mismatch_control/die{DIE}'
    p = json.loads((old/'protocol.json').read_text())
    for f in (Path(__file__), Path(prior.__file__), old/'quality_Cu8.json'):
        p['sources'][str(f)] = legacy.base.fingerprint(f)
    p['Cu_fF'] = [CU]
    p['status'] = 'Frozen paired capacitance/seed extension before new quality results'
    if CU == 6:
        p['modes'] = [['fixed_mismatch_only', 0, False, None]]+[
            ['fixed_mismatch_read20', 20, True, seed] for seed in (60001, 60002)]
    else:
        p['modes'] = [['fixed_mismatch_read20', 20, True, seed] for seed in range(60001, 60009)]
    p['mismatch']['geometry'] = f'Square {CU}*2^bit fF TT PDK area law; same fixed Gaussian physical draws as Cu4/Cu8 controls'
    p['programming_model'] = dict(effective_C_fF_by_unsigned_code=CAPS.tolist(),
        model=('Measured Cu8 unsigned TT AC loading' if CU == 8 else
               'Explicit interpolation: each Cu6 code uses midpoint of actual Cu4 and Cu8 unsigned TT AC loading; not a measured Cu6 circuit'),
        limitation='Ideal signal charge and holder matching; no radix/state/parasitic mismatch or row-DAC error. Cu8 fails8ns dynamic gate; Cu6 timing unverified. No PVT or full-hardware qualification.')
    p['cost'] = f'Installed minimal22-unit magnitude bank {22*CU}fF/weight; two full4bit fixtures {30*CU}fF/weight. Actual active loading and ADC/holder allocation counted separately; no unchanged-delay credit.'
    p['robustness'] = 'Cu8 seeds60001..60008, both existing exposed512-token passages, two existing fixed dies. First two noise seeds must exactly reproduce prior Cu8. Prior mismatch-only diagnostic failures remain part of interpretation. Cu6 uses the original two noise seeds plus diagnostics. No yield or unseen-corpus claim.'
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT/'protocol.json'; text = json.dumps(p, indent=2)+'\n'
    if path.exists(): assert path.read_text() == text
    else: path.write_text(text)
    src, dst = nominal.OUT/'calibration_Cu4.json', OUT/f'calibration_Cu{CU}.json'
    if dst.exists(): assert dst.read_bytes() == src.read_bytes()
    else: dst.write_bytes(src.read_bytes())
    return p


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--die', type=int, choices=(1, 2), default=1)
    ap.add_argument('--cu', type=int, choices=(6, 8), required=True)
    ap.add_argument('--freeze', action='store_true')
    args = ap.parse_args(); DIE, CU = args.die, args.cu
    OUT = ROOT/f'build/campaign/capacitance_robustness/Cu{CU}/die{DIE}'
    CAPS = nominal.loading.CAPS+(CU-4)/4*(prior.CAPS-nominal.loading.CAPS)
    fixed.DIE = DIE
    fixed.coefficient_variance = lambda codes: prior.coefficient_variance(codes, unit=CU)
    legacy.digits, legacy.radix = nominal.digits, nominal.radix
    legacy.OUT, legacy.prepare, legacy.scenes = OUT, nominal.reset.prepare, scenes
    legacy.selfcheck, legacy.freeze, legacy.load = fixed.selfcheck, freeze, fixed.load
    if args.freeze: freeze()
    else: legacy.evaluate(CU)

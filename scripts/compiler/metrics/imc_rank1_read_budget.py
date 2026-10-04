"""Paired0/10/20uV read-noise controls with fixed rank1-calibrated signed8 core."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_mismatch_rank1_quality as rank1
legacy=rank1.legacy
DIE=1
OLD=ROOT/'build/campaign/mismatch_rank1_quality/die1'
OUT=ROOT/'build/campaign/rank1_read_budget/die1'


def freeze():
    p=json.loads((OLD/'protocol.json').read_text())
    p['sources'][str(OLD/'protocol.json')]=legacy.base.fingerprint(OLD/'protocol.json')
    p['sources'][str(Path(__file__))]=legacy.base.fingerprint(__file__)
    p['sources'][str(Path(rank1.__file__))]=legacy.base.fingerprint(rank1.__file__)
    p['formats']=['signed8']
    p['architectures']=[a for a in p['architectures'] if a['label']=='common_A11_separate']
    p['modes']=[[f'fixed_mismatch_read{uv}',uv,True,seed] for uv in (0,10,20) for seed in (60001,60002)]
    p['status']='Frozen read-noise budget control; rank1 factors and physical cap errors unchanged'
    p['selection']='Signed8 A11 separate selected from completed nominal programmed-load grid; lowest worstKL among signed8 separate controls; same two exposed passages, no reserved evaluation'
    p['evaluation']='Always includes corrected kT/C reset/share noise and fixed mismatch. Read0 is ideal-readout lower control; read20 must exactly reproduce matching prior rank1 cases. Two read seeds and both existing512-token passages.'
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    for name in ('calibration_Cu4.json','rank1.npz','rank1.json'):
        src,dst=OLD/name,OUT/name
        assert src.exists(),f'Calibration dependency missing: {src}'
        if dst.exists():assert src.read_bytes()==dst.read_bytes()
        else:dst.write_bytes(src.read_bytes())
    return p


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--die',type=int,choices=(1,2),default=1);ap.add_argument('--freeze',action='store_true');a=ap.parse_args()
    DIE=a.die;OLD=ROOT/f'build/campaign/mismatch_rank1_quality/die{DIE}';OUT=ROOT/f'build/campaign/rank1_read_budget/die{DIE}'
    rank1.DIE=DIE;rank1.OUT=OUT;rank1.fixed.DIE=DIE
    legacy.digits,legacy.radix=rank1.nominal.digits,rank1.nominal.radix
    legacy.OUT,legacy.prepare,legacy.scenes=OUT,rank1.nominal.reset.prepare,rank1.offset.scenes
    legacy.selfcheck,legacy.freeze,legacy.load=rank1.selfcheck,freeze,rank1.load
    legacy.base.Net,legacy.base.quantize=rank1.RankNet,rank1.offset.quantize
    if a.freeze:freeze()
    else:legacy.evaluate(4)

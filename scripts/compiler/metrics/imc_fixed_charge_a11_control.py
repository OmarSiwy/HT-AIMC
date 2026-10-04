"""Additional frozen common-A11 separate control, preserving phase2 unchanged.

Selected because it passed all six completed phase1 development cases. Range
selection still uses only the old calibration stream. No reserved data access.
"""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_fixed_charge_campaign as campaign

campaign.OUT=ROOT/'build/campaign/fixed_charge_a11'
campaign.PROTOCOL=campaign.OUT/'protocol.json'
original_load=campaign.load


def load_with_control_source():
    result=original_load()
    source=Path(__file__).resolve()
    digest=campaign.fingerprint(source)
    result[-1][str(source)]=digest
    snapshot=campaign.OUT/f'control_source_{digest}.py'
    if not snapshot.exists():snapshot.write_bytes(source.read_bytes())
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibrate',action='store_true')
    parser.add_argument('--bits',type=int,choices=(10,11,12),default=12)
    parser.add_argument('--cu',type=int,choices=(4,8,16,32),default=4)
    args=parser.parse_args()
    campaign.load=load_with_control_source
    if args.calibrate:campaign.calibrate()
    else:campaign.evaluate(args.bits,args.cu)

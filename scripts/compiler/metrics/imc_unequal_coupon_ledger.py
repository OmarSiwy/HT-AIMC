"""Independent noise/footprint audit of actual unequal grounded MIM coupons."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]


def main():
    old=ROOT/'build/campaign/mim_units_contact_electrical_r1/result.json'
    new=ROOT/'build/campaign/mim_unequal_contact_electrical_r1/result.json'
    baseline=next(r for r in json.loads(old.read_text())['rows'] if r['width_nm']==1260)
    data=json.loads(new.read_text());assert data['pass_matrix_audit']
    low=next(r for r in data['rows'] if r['width_nm']==1000)
    high=next(r for r in data['rows'] if r['width_nm']==1360)
    def calculate(lo,hi,group,read_uV):
        cs=[120+group*n*(r['mutual_cap_fF']+r['bottom_substrate_fF']) for n,r in [(7,lo),(15,hi)]]
        signal=[lo['mutual_cap_fF'],hi['mutual_cap_fF']]
        thermal=sum(w*2*1.380649e-23*300*1e15*c/cu**2 for w,c,cu in zip([1,64],cs,signal))
        read=sum(w*(read_uV*1e-6*c/cu)**2 for w,c,cu in zip([1,64],cs,signal))
        return dict(native_C_fF=cs,signal_Cu_fF=signal,thermal=thermal,read=read,total=thermal+read,
                    footprint_um2=7*lo['bottom_footprint_um2']+15*hi['bottom_footprint_um2'],
                    mutual_fF_per_site=7*signal[0]+15*signal[1])
    rows=[]
    for group in [32,64,128]:
        for noise in [40,50,67]:
            a=calculate(baseline,baseline,group,noise);b=calculate(low,high,group,noise)
            assert b['footprint_um2']<=a['footprint_um2']
            rows.append(dict(group=group,read_uV=noise,baseline=a,candidate=b,
                             ratios={k:b[k]/a[k] for k in ['thermal','read','total','footprint_um2','mutual_fF_per_site']}))
    result=dict(status='VERIFIED independent lumped arithmetic using extracted coupon matrices; no array quality or transistor timing claim',
                sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [old,new,Path(__file__)]},
                scope='Two independent equal signal/reference holders at300K;120fF perbank floor; nativeC includes mutual plus bottomSUB, signal recovery uses mutualCu only. Radix8 yields highbankvariance weight64. Common input/group gain omitted, not gaincalibrated away. No CDAC, route/MOS extraC, matching, dynamic transfer or denominator error.',
                rows=rows)
    out=ROOT/'build/campaign/grounded_unequal_actual_coupon_ledger.json';assert not out.exists()
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(rows[1],indent=2));print('PASS independent actual-coupon budget and noise audit')


if __name__=='__main__':main()

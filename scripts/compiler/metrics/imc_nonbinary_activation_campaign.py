"""Shared robust signed-digit activation encoding; hypothetical radix intervals."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'build/campaign/nonbinary_activation'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def powers(r, planes):
    """Same ideal per-column zero/full-scale gain calibration for every code."""
    r = np.asarray(r)
    gain = 511/np.sum(r[:,None]**np.arange(9), axis=1)
    return gain[:,None]*r[:,None]**np.arange(planes)


def ternary(planes):
    k = np.arange(3**planes, dtype=np.int32)
    return ((k[:,None]//(3**np.arange(planes)))%3-1).astype(np.int8)


def binary(planes):
    result = np.zeros((512,planes), dtype=np.int8)
    result[:,:9] = (np.arange(512)[:,None] >> np.arange(8,-1,-1)) & 1
    return result


def costs(digits):
    physical_order = np.pad(digits[:,::-1].astype(np.int16), ((0,0),(1,1)))
    transitions = np.sum(np.diff(physical_order,axis=1)**2,axis=1)
    return transitions, np.count_nonzero(digits,axis=1)


def select(planes, rgrid):
    digits = ternary(planes)
    values = digits.astype(float)@powers(rgrid,planes).T
    nominal = values[:,len(rgrid)//2]
    order = np.argsort(nominal,kind='stable')
    ordered = nominal[order]
    transitions, active = costs(digits)
    base = binary(planes)
    base_error = abs(base@powers(rgrid,planes).T-np.arange(512)[:,None]).max(axis=1)
    selected, error, searched = [], [], []
    for target, bound in enumerate(base_error):
        # Any candidate beating the binary upper bound must satisfy this
        # necessary nominal-error bound; no heuristic candidates are dropped.
        lo = np.searchsorted(ordered,target-bound-1e-10,'left')
        hi = np.searchsorted(ordered,target+bound+1e-10,'right')
        candidates = order[lo:hi]
        e = abs(values[candidates]-target).max(axis=1)
        best = e.min()
        tied = candidates[e <= best+1e-12]
        chosen = tied[np.lexsort((tied,active[tied],transitions[tied]))[0]]
        selected.append(chosen);error.append(float(abs(values[chosen]-target).max()))
        searched.append(len(candidates))
    selected = digits[selected]
    error = np.array(error)
    assert np.all(error <= base_error+1e-10)
    assert not np.any(selected[0])
    return selected,dict(max_error=float(error.max()),rms_worst_case_error=float(np.sqrt(np.mean(error**2))),
                         binary_max_error=float(base_error.max()),binary_rms_worst_case_error=float(np.sqrt(np.mean(base_error**2))),
                         candidate_count=len(digits),scored_candidates_total=int(sum(searched)),
                         maximum_scored_candidates_one_target=max(searched))


def metrics(table, ratios):
    residual=table@powers(ratios,table.shape[1]).T-np.arange(512)[:,None]
    transition,active=costs(table)
    return dict(max_abs_code_error=float(abs(residual).max()),rms_code_error=float(np.sqrt(np.mean(residual**2))),
                mean_active_digits=float(active.mean()),mean_reset_each_plane_energy_units=float(2*active.mean()),
                mean_persistent_driver_transition_energy_units=float(transition.mean()),
                worst_code_error_by_r=abs(residual).max(axis=0).tolist())


def dot_metrics(q, w, table, ratios):
    # One table shared by every row and output column; only physical r varies.
    actual=np.zeros((len(q),len(w)))
    sign=np.sign(q)
    ratios=np.broadcast_to(ratios,(2,len(w)))
    for bank,weight in enumerate((np.sign(w)*(abs(w)%16),np.sign(w)*(abs(w)//16))):
        for col,r in enumerate(ratios[bank]):
            values=table@powers(np.array([r]),table.shape[1]).T
            actual[:,col]+=16**bank*((values[abs(q),0]*sign)@weight[col])
    expected=q.astype(float)@w.T
    error=actual-expected
    t,a=costs((table[abs(q)]*sign[:,:,None]).reshape(-1,table.shape[1]))
    return dict(dot_RMS_MAC=float(np.sqrt(np.mean(error**2))),dot_max_MAC=float(abs(error).max()),
                dot_NMSE=float(np.sum(error**2)/np.sum(expected**2)) if np.any(expected) else None,
                mean_active_digits_per_input=float(a.mean()),mean_transition_units_per_input=float(t.mean()),
                fixed_plane_events=int(len(q)*q.shape[1]*table.shape[1]),
                cancellation_condition_max=float(np.max((abs(q)@abs(w).T)/np.maximum(abs(expected),1))))


def selfcheck():
    base=binary(11)
    assert np.array_equal(base@powers(np.array([.5]),11).T,np.arange(512)[:,None])
    d=ternary(5);assert d.shape==(243,5) and len(np.unique(d,axis=0))==243
    rng=np.random.default_rng(97340)
    ds=rng.integers(-1,2,(31,11));r=.503
    h=np.zeros(len(ds))
    for digit in ds[:,::-1].T:h=r*h+r*digit
    gain=511/np.sum(r**np.arange(9))
    assert np.allclose(h*gain/r,ds@powers(np.array([r]),11).T[:,0],atol=1e-12)
    # Shared encoding remains exactly antisymmetric for negative operands.
    q=rng.integers(-511,512,(7,16));w=rng.integers(-127,128,(8,16))
    result=dot_metrics(q,w,base,np.full(8,.5))
    assert result['dot_max_MAC']==0


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    fixtures={name:ROOT/f'build/campaign/system_audit/physical_fixture/{name}/fixture.npz' for name in ('p50','p95')}
    sources={str(Path(__file__).resolve()):sha(__file__),**{str(p):sha(p) for p in fixtures.values()}}
    protocol=dict(sources=sources,planes=[9,10,11],intervals=[[.499,.501],[.502,.504]],
                  selection_grid_points=11,audit_grid_points=1001,seed=97341,
                  calibration='Ideal exact zero and511 output gain at each physical column r; same calibration for binary and ternary',
                  selection='One activation lookup per interval/plane count, exhaustive sampled-grid minimax; nominal-error bound only prunes impossible winners; ties1e-12 then transition, active count, index',
                  independent_tests='Frozen real p50/p95 W8 low/high slices with independent per-slice column r shared across all plane counts; existing3 development words, plus128 uniform and128 clipped heavy-tail fixed-seed words',
                  allowed_digits=[-1,0,1],negative_codes='Exact sign inversion of positive lookup',
                  costing='All9/10/11 planes paid; two driver-energy proxies and2-bit/digit table storage; no hardware energy/area inferred',
                  qualification='Hypothetical r intervals only; no circuit/model-quality or new held-out corpus claim')
    encoded=(json.dumps(protocol,indent=2)+'\n').encode();pp=OUT/'protocol.json'
    if pp.exists():assert pp.read_bytes()==encoded,'Frozen protocol changed'
    else:pp.write_bytes(encoded)
    (OUT/f'source_{sha(__file__)}.py').write_bytes(Path(__file__).read_bytes())
    selfcheck();tables={};results=[]
    for index,(low,high) in enumerate(protocol['intervals']):
        grid=np.linspace(low,high,protocol['selection_grid_points'])
        audit=np.linspace(low,high,protocol['audit_grid_points'])
        for planes in protocol['planes']:
            table,selection=select(planes,grid);key=f'r{index}_B{planes}'
            tables[key]=table
            selected=metrics(table,audit);control=metrics(binary(planes),audit)
            record=dict(key=key,interval=[low,high],planes=planes,selection=selection,selected=selected,binary=control,
                        cycles_vs_binary9=planes/9,lookup_bits=512*planes*2,
                        classification='VERIFIED sampled-grid minimax; dense-grid interval check only')
            results.append(record)
            print(key,'maximum',selected['max_abs_code_error'],'binary',control['max_abs_code_error'],flush=True)
    np.savez(OUT/'frozen_tables.npz',**tables)
    frozen_table_hash=sha(OUT/'frozen_tables.npz')
    # Calibration/selection ends here, before weighted test inputs are generated.
    rng=np.random.default_rng(protocol['seed']);tests=[]
    for name,path in fixtures.items():
        fixture=np.load(path)
        w=fixture['Wq'].astype(float)
        assert w.shape==(8,256)
        inputs={'uniform':rng.integers(-511,512,(128,256)),
                'heavy_tail':np.clip(np.rint(rng.standard_t(3,(128,256))*64),-511,511).astype(int),
                'development_words':fixture['xq'].astype(int)}
        column_ratios={tuple(interval):rng.uniform(*interval,(2,8)) for interval in protocol['intervals']}
        for result in results:
            ratios=column_ratios[tuple(result['interval'])]
            for pattern,q in inputs.items():
                for method,table in [('binary',binary(result['planes'])),('shared_ternary',tables[result['key']])]:
                    tests.append(dict(fixture=name,key=result['key'],pattern=pattern,method=method,ratios=ratios.tolist(),
                                      **dot_metrics(q,w,table,ratios)))
    assert sha(OUT/'frozen_tables.npz')==frozen_table_hash
    assert all(sha(p)==h for p,h in sources.items()) and pp.read_bytes()==encoded
    report=dict(protocol_sha256=hashlib.sha256(encoded).hexdigest(),table_sha256=frozen_table_hash,
                results=results,weighted_tests=tests,classification=protocol['qualification'])
    (OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: recurrence, binary/antisymmetry, exact candidate pruning, calibration freeze, finite weighted tests')


if __name__=='__main__':main()

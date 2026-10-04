"""Finite low14/high13 charge guards with paid native-CDAC capacitance.

Separate and pooled mappings independently fit old calibration ranges. Host and
distributed-capacitor policies share those ranges. Distributed plates are an
integer-unit placement model, not transistor/layout validation.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_fixed_charge_campaign as base
import numpy as np

OUT=ROOT/'build/campaign/charge_guard'
BITS=(14,13)


def geometry(units,bank,policy,cu):
    u=3.75*cu/4;nbits=BITS[bank];seen=2**(nbits-4)*u
    caps=120+cu*units.astype(float)
    raw=caps.copy()
    target=2**(nbits-4)
    if policy=='host':
        pad=np.maximum(seen-caps[0],0)
        caps[0]+=pad
        fragments=np.full(caps.shape[1],nbits-4,dtype=int)
    else:
        # Coarse fragments are integer multiples of u. Small fractional
        # remainders remain unswitched matching capacitance.
        available=np.floor(caps/u+1e-12).astype(int)
        missing=np.maximum(target-available.sum(axis=0),0)
        remainder=caps[0]-available[0]*u
        pad=np.where(missing>0,missing*u-remainder,0.)
        caps[0]+=pad
        available=np.floor(caps/u+1e-12).astype(int)
        available[0]-=1  # Fine bridge presents one equivalent u at host0.
        fragments=np.zeros(caps.shape[1],dtype=int)
        for bit in range(nbits-5,-1,-1):
            required=np.full(caps.shape[1],2**bit,dtype=int)
            for g in range(len(caps)):
                take=np.minimum(required,available[g])
                available[g]-=take;required-=take
                fragments+=(take>0)
            assert not np.any(required)
    assert np.all(pad>=0)
    total=caps.sum(axis=0)
    stats=dict(hosts=len(total),padded_hosts=int(np.count_nonzero(pad)),
        two_sided_padding_fF=float(2*pad.sum()),
        connected_array_holder_and_DAC_excess_fF=float(2*caps.sum()+len(total)*(16+1/15)*u),
        max_original_host_fF=float(raw[0].max()),max_padded_host_fF=float(caps[0].max()),
        max_joined_fF=float(total.max()),max_padding_fF=float(pad.max()),
        coarse_switch_fragments=int(fragments.sum()),max_coarse_fragments_per_ADC=int(fragments.max()),
        native_coarse_bits=nbits-4)
    return caps,stats


def read(bank,bank_index,policy,cu,span,read_uv=0,thermal=False,rng=None,ideal=False):
    nbits=BITS[bank_index];u=3.75*cu/4;step=u/16*span
    out=np.zeros(bank[0]['Q_per_Cu'].shape,dtype=float)
    tally=Counter(conversions=0,ADC_decisions=0,clips=0,boundary12_events=0,
                  additional_coarse_packets=0,column_plane_events=0)
    peaks={};boundaries=[];depths=[];packets=[]
    for scene in bank:
        caps,static=geometry(scene['units'],bank_index,policy,cu)
        for k,v in static.items():
            if k.startswith('max_'):peaks[k]=max(peaks.get(k,0),v)
            elif k!='native_coarse_bits':tally[k]+=v
        C=caps.sum(axis=0);Q=cu*scene['Q_per_Cu'];active=scene['active'][:,None]
        tally['conversions']+=int(active.sum())*Q.shape[1]
        tally['ADC_decisions']+=nbits*int(active.sum())*Q.shape[1]
        tally['column_plane_events']+=int(scene['B'].sum())*len(caps)*Q.shape[1]
        if thermal or read_uv:
            assert rng is not None
            variance=np.broadcast_to((C[None,:]*read_uv*1e-6)**2,Q.shape).copy()
            if thermal:
                variance+=base.KT*1e15*C[None,:]/2*(1-4.**(-scene['B'][:,None]))/(1-.25)
            Q=Q+rng.standard_normal(Q.shape)*np.sqrt(variance)
        code=np.floor(Q/step+.5)
        boundary=((code<=-2048)|(code>=2047))&active
        signed_packets=np.floor((code+2048)/4096)
        signed_packets[~np.broadcast_to(active,code.shape)]=0
        magnitude=np.where(code<0,-code,code+1)
        depth=np.maximum(np.ceil(np.log2(np.maximum(magnitude,1)))-11,0).astype(int)
        depth[~np.broadcast_to(active,code.shape)]=0
        boundaries.append(boundary);depths.append(depth);packets.append(abs(signed_packets))
        tally['boundary12_events']+=int(boundary.sum())
        tally['additional_coarse_packets']+=int(abs(signed_packets).sum())
        tally['clips']+=int((((code < -2**(nbits-1)) | (code > 2**(nbits-1)-1))&active).sum())
        peaks['max_abs_charge_fC']=max(peaks.get('max_abs_charge_fC',0),float(abs(Q).max()))
        peaks['max_abs_held_V']=max(peaks.get('max_abs_held_V',0),float(abs(Q/C[None,:]).max()))
        if not ideal:Q=np.clip(code,-2**(nbits-1),2**(nbits-1)-1)*step
        got=Q*np.exp2(scene['B'][:,None])/(cu*.45)*scene['dx'][:,None]
        got[~scene['active']]=0;out+=got
    boundary=np.concatenate(boundaries,axis=1)
    depth=np.concatenate(depths,axis=1)
    packet=np.concatenate(packets,axis=1)
    # Workload-intrinsic statistics, independent of ADC assignment.
    maxdepth=depth.max(axis=1);maxpacket=packet.max(axis=1)
    tally.update(token_bank_steps_with_boundary=int(np.any(boundary,axis=1).sum()),
                 token_bank_steps=len(boundary))
    peaks.update(max_boundary_events_one_token=int(boundary.sum(axis=1).max()),
                 max_extra_code_bits=int(maxdepth.max()),max_abs_packet_count=int(maxpacket.max()))
    histogram=dict(extra_bits=dict(Counter(map(int,maxdepth))),
                   packets=dict(Counter(map(int,maxpacket))))
    return out,dict(tally,**peaks,ADC_bits=nbits,Cu_fF=cu,Vspan_V=span,
                   deltaQ_fC=step,token_maximum_histogram=histogram),boundaries,depths


def stalls(boundaries,pooled):
    """Conditional 256-ADC scheduling per logical1024-row/1024-column tile.

    Reports rounds with any 12-bit endpoint requiring escalation. It does not
    turn rare event counts into actual measured time or assume a free queue.
    """
    totals=Counter(conditional_tile_token_steps=0,conditional_ADC_rounds=0,
                   conditional_rounds_with_boundary=0,conditional_tile_steps_with_boundary=0)
    maximum=0
    for first in range(0,len(boundaries),1 if pooled else 4):
        scenes=boundaries[first:first+(1 if pooled else 4)]
        for col in range(0,scenes[0].shape[1],1024):
            events=np.concatenate([b[:,col:col+1024] for b in scenes],axis=1)
            rounds=(events.shape[1]+255)//256
            pad=(-events.shape[1])%256
            if pad:events=np.pad(events,((0,0),(0,pad)))
            flagged=np.any(events.reshape(len(events),rounds,256),axis=2)
            totals.update(conditional_tile_token_steps=len(events),
                conditional_ADC_rounds=rounds*len(events),
                conditional_rounds_with_boundary=int(flagged.sum()),
                conditional_tile_steps_with_boundary=int(np.any(flagged,axis=1).sum()))
            maximum=max(maximum,int(flagged.sum(axis=1).max()))
    return dict(totals,max_boundary_rounds_one_tile_token=maximum)


def selfcheck():
    rng=np.random.default_rng(41901)
    for groups in (1,3,4):
        units=rng.integers(0,3500,(groups,29)).astype(float)
        for b in (0,1):
            a,ast=geometry(units,b,'host',4)
            d,dst=geometry(units,b,'distributed',4)
            assert d.sum()<=a.sum()+1e-8
            assert np.all(np.floor(d/3.75+1e-12).sum(axis=0)>=2**(BITS[b]-4))
            assert dst['max_coarse_fragments_per_ADC']<=BITS[b]-4+groups-1
            if groups==1:assert np.allclose(a,d,rtol=0,atol=1e-9)
    q=rng.integers(-511,512,(13,1093),dtype=np.int16)
    q[0]=0;w=rng.integers(-127,128,(1093,5),dtype=np.int16)
    for pooled in (False,True):
        bs=base.scenes(q,w,np.ones((13,5)),pooled)
        for policy in ('host','distributed'):
            parts=[read(b,i,policy,4,.5,ideal=True)[0] for i,b in enumerate(bs)]
            assert np.allclose(parts[0]+16*parts[1],q.astype(float)@w,atol=1e-7,rtol=1e-12)
        if not pooled:
            for b,scene in enumerate(bs):
                a=read(scene,b,'host',4,.5,20,True,np.random.default_rng(214))[0]
                d=read(scene,b,'distributed',4,.5,20,True,np.random.default_rng(214))[0]
                assert np.allclose(a,d,atol=1e-8,rtol=1e-12)
    edge=np.zeros((3,768),dtype=bool);edge[0,0]=True;edge[0,256]=True;edge[1,-1]=True
    score=stalls([edge],True)
    assert score['conditional_ADC_rounds']==9 and score['conditional_rounds_with_boundary']==3
    assert score['conditional_tile_steps_with_boundary']==2 and score['max_boundary_rounds_one_tile_token']==2
    print('PASS: integer-unit distributed fit, matched padding, noisy separate-policy parity, exact charge and conditional stall counts',flush=True)


def load():
    p=json.loads((OUT/'protocol.json').read_text())
    _,old,net,weights,sources=base.load()
    for f in (Path(__file__),OUT/'protocol.json'):sources[str(f)]=base.fingerprint(f)
    (OUT/f'source_{base.fingerprint(__file__)}.py').write_bytes(Path(__file__).read_bytes())
    return p,old,net,weights,sources


def calibrate():
    selfcheck();p,old,net,weights,sources=load()
    output=OUT/'calibration.json';assert not output.exists()
    notes=Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute'
    note=next(notes.glob('27h3 *.md'));sources[str(note)]=base.fingerprint(note)
    ids=base.tokenize_greedy(note.read_text(),net.vocab)[:128]
    activations={}
    def capture(li,name,a,w,y):activations[li,name]=a.copy();return y
    net.mvm=capture;net(ids);net.mvm=None;assert len(activations)==210
    records=[]
    for arch in p['architectures']:
        for (li,name),(s,w,dw) in weights.items():
            q,dx,_=base.quantize(activations[li,name]/s,arch['kind'],arch['A'])
            for bank,b in enumerate(base.scenes(q,w,dx,arch['pooled'])):
                target=base.reconstruct(b,4,12,.5,ideal=True)[0]*dw
                grid=[]
                for span in p['Vspan_grid_V']:
                    got,counts,_,_=read(b,bank,'host',4,span)
                    grid.append(dict(Vspan_V=span,MSE=float(np.mean((got*dw-target)**2)),
                        clips=counts['clips'],boundary12_events=counts['boundary12_events'],
                        maxQ_fC=counts['max_abs_charge_fC']))
                best=min(grid,key=lambda g:g['MSE'])
                records.append(dict(architecture=arch['label'],layer=li,tensor=name,bank=bank,
                    ADC_bits=BITS[bank],selected_Vspan_V=best['Vspan_V'],grid=grid))
            if (li+1)%5==0 and name==base.TENSORS[-1]:print('calibration',arch['label'],li+1,flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    output.write_text(json.dumps(dict(complete=True,protocol=p,sources=sources,records=records),indent=2)+'\n')
    print('PASS frozen old-stream independent guard calibration',flush=True)


def evaluate(policy,cu):
    selfcheck();p,old,net,weights,sources=load()
    assert policy in p['policies'] and cu in p['Cu_fF']
    oracle=ROOT/'build/campaign/charge_noise_oracle/results.json'
    assert json.loads(oracle.read_text())['complete'],'Complete optimistic noise bound before finite quality evaluation'
    sources[str(oracle)]=base.fingerprint(oracle)
    calpath=OUT/'calibration.json';cal=json.loads(calpath.read_text())
    assert cal['complete'] and all(base.fingerprint(f)==h for f,h in cal['sources'].items())
    sources[str(calpath)]=base.fingerprint(calpath)
    ranges={(r['architecture'],r['layer'],r['tensor'],r['bank']):r['selected_Vspan_V'] for r in cal['records']}
    output=OUT/f'{policy}_Cu{cu}.json';assert not output.exists()
    results=[];report=dict(complete=False,protocol=p,sources=sources,policy=policy,Cu_fF=cu,results=results,
        classification='Finite charge-range/matched-padding/noise model; no distributed transistor/PEX/reference or timing validation')
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for arch in p['architectures']:
            for mode,read_uv,thermal,seed in p['modes']:
                rng=np.random.default_rng(seed);tensors=[];started=time.perf_counter()
                def compute(li,name,a,w,clean):
                    s,wq,dw=weights[li,name]
                    q,dx,_=base.quantize(a/s,arch['kind'],arch['A'])
                    parts=[];counts=[]
                    for bank,b in enumerate(base.scenes(q,wq,dx,arch['pooled'])):
                        y,c,boundaries,_=read(b,bank,policy,cu,ranges[arch['label'],li,name,bank],read_uv,thermal,rng)
                        c.update(stalls(boundaries,arch['pooled']));parts.append(y);counts.append(c)
                    tensors.append(dict(layer=li,tensor=name,banks=counts))
                    return ((parts[0]+16*parts[1])*dw).astype(np.float32)
                net.mvm=compute;metrics=ev.score(net(ids));assert len(tensors)==210
                keys=('conversions','ADC_decisions','clips','boundary12_events','additional_coarse_packets',
                      'column_plane_events','two_sided_padding_fF','connected_array_holder_and_DAC_excess_fF',
                      'coarse_switch_fragments','conditional_ADC_rounds','conditional_rounds_with_boundary',
                      'conditional_tile_token_steps','conditional_tile_steps_with_boundary','token_bank_steps_with_boundary')
                total={k:sum(b[k] for t in tensors for b in t['banks']) for k in keys}
                maxima={k:max(b[k] for t in tensors for b in t['banks']) for k in
                        ('max_joined_fF','max_padding_fF','max_extra_code_bits','max_abs_packet_count',
                         'max_boundary_rounds_one_tile_token','max_abs_charge_fC')}
                r=dict(source=note.name,architecture=arch['label'],mode=mode,seed=seed,**metrics,
                    **total,**maxima,tensors=tensors,runtime_s=time.perf_counter()-started,
                    joint_pass=metrics['kl']<=.01 and metrics['ppl_ratio']<=1.01)
                results.append(r);output.write_text(json.dumps(report,indent=2)+'\n')
                print(policy,cu,note.stem[:12],arch['label'],mode,seed,
                    {k:r[k] for k in ('kl','ppl_ratio','joint_pass','clips','boundary12_events')},flush=True)
        net.mvm=None;assert np.array_equal(net(ids),ev.ref)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    report['complete']=True;output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS guard-model execution; quality',sum(r['joint_pass'] for r in results),'/',len(results),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selfcheck',action='store_true')
    parser.add_argument('--calibrate',action='store_true')
    parser.add_argument('--policy',choices=('host','distributed'),default='host')
    parser.add_argument('--cu',type=int,choices=(4,8,16,32),default=4)
    args=parser.parse_args()
    if args.selfcheck:selfcheck()
    elif args.calibrate:calibrate()
    else:evaluate(args.policy,args.cu)

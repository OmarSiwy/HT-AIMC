"""Reproducible capacity and local arithmetic-sharing bounds, not physical PPA."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
M=106168320
MYTHIC_WEIGHTS=79691776
CU_FF=4
UNITS=22
DENSITY_FF_UM2=2
SRAM_BIT_UM2=1.896


def bounds(weights, sharing, service_ns, reuse=1):
    assert weights>0 and sharing>=1 and service_ns>0 and reuse>=1
    storage=8*weights*SRAM_BIT_UM2/1e6
    capacitor=2*weights*UNITS*CU_FF/DENSITY_FF_UM2/sharing/1e6
    latency=sharing*service_ns
    throughput=2*weights/(latency*1e-9)
    return dict(weights=weights,sharing=sharing,service_ns=service_ns,reuse_vectors=reuse,
        bare_singleport_storage_mm2=storage,nominal_capacitor_mm2=capacitor,
        ideal_all_metal_overlap_lower_envelope_mm2=max(storage,capacitor),
        disjoint_footprint_without_periphery_mm2=storage+capacitor,
        all_weights_service_sweep_ns=latency,
        ideal_fully_utilized_native_TOPS=throughput/1e12,
        explicit_digital_read_payload_Tbit_s=8/reuse*throughput/2/1e12)


def main():
    rows=[bounds(M,s,t,b) for t in (250,500,1000) for b in (1,8,32) for s in (1,2,4,8,9,16,32,64)]
    for t in (250,500,1000):
        v=[r for r in rows if r['service_ns']==t and r['reuse_vectors']==1]
        assert all(v[i]['disjoint_footprint_without_periphery_mm2']>v[i+1]['disjoint_footprint_without_periphery_mm2'] for i in range(len(v)-1))
        assert all(v[i]['all_weights_service_sweep_ns']<v[i+1]['all_weights_service_sweep_ns'] for i in range(len(v)-1))
        products=[r['disjoint_footprint_without_periphery_mm2']*r['all_weights_service_sweep_ns'] for r in v]
        assert all(products[i]<products[i+1] for i in range(len(products)-1))
    out=ROOT/'build/campaign/storage_sharing_bounds';out.mkdir(parents=True,exist_ok=True)
    path=out/'result.json';assert not path.exists()
    result=dict(status='VERIFIED_ARITHMETIC_CONDITIONAL_ARCHITECTURE_ENVELOPES',
        scope='Service times250/500/1000ns are scenarios, not measured completeW8 converter times. Allweights simultaneous utility is an upper envelope, not transformer DAG throughput. No measuredSRAMreadenergy or finalPPA.',
        source_values=dict(weights=M,observed_weight_support=[-127,127],Cu_fF=CU_FF,installed_magnitude_units_per_weight=UNITS,
            nominal_single_layer_cap_density_fF_um2=DENSITY_FF_UM2,bare_foundry_singleport_bitcell_um2=SRAM_BIT_UM2,
            bitcell_source='https://escholarship.org/content/qt9dc0v8g3/qt9dc0v8g3.pdf',
            public_dualport_1kB_LEF_size_um=[479.78,397.5],
            LEF_source='https://raw.githubusercontent.com/VLSIDA/sky130_sram_macros/main/sky130_sram_1kbyte_1rw1r_32x256_8/sky130_sram_1kbyte_1rw1r_32x256_8.lef'),
        full_resident_nominal_cap_mm2=2*M*UNITS*CU_FF/DENSITY_FF_UM2/1e6,
        mythic_capacity_nominal_cap_mm2=2*MYTHIC_WEIGHTS*UNITS*CU_FF/DENSITY_FF_UM2/1e6,
        public_1kB_macro_replicated_capacity_mm2=M/1024*479.78*397.5/1e6,
        nominal_cap_vs_bare_storage_knee=2*UNITS*CU_FF/DENSITY_FF_UM2/(8*SRAM_BIT_UM2),
        explicit_read_bandwidth_at_16p6TOPS_Tbit_s={str(b):8*16.6/2/b for b in (1,8,32)},
        read_energy_break_even_fJ_per_bit_at_3p3TOPS_W={str(compute):((2/3.3)*1000-compute)/8 for compute in (50,100,200,400)},
        rows=rows)
    path.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS capacity, sharing monotonicity, area-latency tradeoff, and explicit-read bandwidth bounds')


if __name__=='__main__':main()

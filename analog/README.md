# analog/

One directory per block. Each block has `netlist/`, `va/` (Verilog-A golden model),
`test/`, `docs/architecture.md`, `schematics/`, `layout/`, `build/` and `output/`.
Follow the `analog-design-flow` skill. System specs and the full signal chain are in
[`docs/architecture.md`](docs/architecture.md).

## Chip 1: MVM path (`analogioc`)

```mermaid
flowchart LR
    rail[["digital rail / compiler<br/>(outside analog/)"]]
    ctrl[async_ctrl<br/>tq_chain + Muller-C]
    pwm[pwm_driver x16]
    tile[weight_tile<br/>16 x 17 cap crossbar]
    conv[integrator_conv x17<br/>integrator + event-rate + 4b SAR]
    ladder[rstring_ladder x4]
    lora[lora_sidecar<br/>rank-1 LoRA]
    kv[gain_cell_array<br/>K,V 8x8]
    wdac[write_dac x8]
    sm[translinear_softmax]

    rail -- "INT8 act as 2x4b PWM" --> pwm
    ctrl -- "t_q taps, phases" --> pwm
    pwm -- "outa/outb" --> tile
    tile -- "col j (charge)" --> conv
    lora -- "colb j (charge sum)" --> conv
    kv -- "kcol/vcol (charge sum)" --> conv
    wdac -- "wd0..7 write bus" --> kv
    ladder -- "thr_p/n, sar_p/n" --> conv
    conv -- "col_code 8b, done" --> rail
    sm -- "A.V drive currents" --> kv
```

## Block hierarchy

```mermaid
flowchart TD
    analogioc --> async_ctrl & gain_cell_array & integrator_conv & lora_sidecar & ota & rstring_ladder & translinear_softmax & weight_tile & write_dac
    chip2_attention --> gain_cell_array & ptat_bias & rescale & softmax_combine & translinear_softmax & wta
    chip_supertile --> integrator_conv
    integrator_conv --> cmos_switch & ota & pwm_driver & strongarm
    lora_sidecar --> cmos_switch & gain_cell_array & ota & write_dac
    weight_tile --> cmos_switch & pwm_driver
    gain_cell_array --> cmos_switch
    write_dac --> cmos_switch
    rstring_ladder --> cmos_switch
```

| Block                                            | Role                                                  |
| ------------------------------------------------ | ----------------------------------------------------- |
| `ota`                                            | Telescopic-cascode OTA, column integrator amplifier   |
| `strongarm`                                      | Clocked latch comparator (coarse loop, SAR trials)    |
| `cmos_switch`                                    | Transmission gate: steering, resets, tap muxes        |
| `pwm_driver`                                     | PWM envelope onto the two-phase SC grid               |
| `async_ctrl`                                     | Self-timed sequencer + `tq_chain` t_q tap line        |
| `ptat_bias`                                      | PTAT reference, softmax-class tail bias               |
| `rescale`                                        | Translinear ratio pair, g = exp(beta dV) <= 1         |
| `softmax_combine`                                | Level-1 group logsumexp over banks' V_ls              |
| `translinear_softmax`                            | 8-input subthreshold softmax, source node = logsumexp |
| `wta`                                            | Source-follower running max with replica VGS cancel   |
| `gain_cell_array`                                | 8x8 2T gain cells, column write, PWM row read         |
| `write_dac`                                      | 4b R-string DAC, programs gain cells                  |
| `rstring_ladder`                                 | 4b R-string, converter thresholds and SAR span        |
| `weight_tile`                                    | 16x(16+1) charge-domain crossbar, 4b diff cap banks   |
| `integrator_conv`                                | Column converter: integrator, event-rate loop, 4b SAR |
| `lora_sidecar`                                   | Rank-1 LoRA summing onto tile columns                 |
| `analogioc`, `chip2_attention`, `chip_supertile` | Top-level assemblies                                  |

Shared python lives in `common/` (bench, corners, devices, pex, substrate2 layout).
Components that other projects will reuse go in `library/` (submodule, see `AGENTS.md`).

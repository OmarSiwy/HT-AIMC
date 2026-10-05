"""Behavioural stand-ins around conv_seq / tile_seq testbenches (INTERFACE.md §9: "an
ideal tile_fsm stand-in"). Event-driven Verilog-A in this directory, simulated by ESPice
through VerA (`.hdl`):

  rtl_standin.va   tile_fsm + event_ctrl + sar_ctrl for one conversion (2FF latency at
                   T_CLK_MAX): sdone cb_req cb_cross cmp_ack cmp_result -> coarse_en cb_ack
                   cmp_req ota_en b3 b2 b1 b0 rtl_done
  sa1_standin.va   dual-rail SA1: crossings for the first n_cross coarse strobes
  sa2_standin.va   dual-rail SA2 (sign 1): keep the trial iff fine >= dac_code
  seq_drv.va       integ_req for n_pass handshakes + 17 sdone following sgo

Each helper adds the model and one instance to a wrapper Subcircuit.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
A = HERE.parents[1]
sys.path[:0] = [str(A / "docs")]
from pdk_specs import get_pdk  # noqa: E402

T_CLK = 20e-9            # fabric clock = T_CLK_MAX (the slowest the contract allows)
T_SYNC = 2 * T_CLK       # 2FF synchroniser latency
VDD = get_pdk().vdd
RTL_NETS = ["sdone", "cb_req", "cb_cross", "cmp_ack", "cmp_result", "coarse_en", "cb_ack",
            "cmp_req", "ota_en", "b3", "b2", "b1", "b0", "rtl_done"]


def _add(top, module, inst, nets, **params):
    top.veriloga(str(HERE / f"{module}.va"))
    card = " ".join(f"{k}={v}" for k, v in dict(vdd=VDD, **params).items())
    top.raw_spice(f".model {inst}_m {module} {card}")
    top.raw_spice(f"N{inst} {' '.join(nets)} {inst}_m")


def rtl(top, nets=RTL_NETS):
    _add(top, "rtl_standin", "rtl", nets, t_sync=T_SYNC)


def sa1(top, n_cross):
    _add(top, "sa1_standin", "sa1", ["clk_c", "c1p", "c1n"], n_cross=n_cross)


def sa2(top, fine):
    _add(top, "sa2_standin", "sa2", ["clk_f", "b3", "b2", "b1", "b0", "c2p", "c2n"], fine=fine)


def seq_drv(top, n_pass, t_req, n_cols):
    _add(top, "seq_drv", "drv", ["integ_ack", "sgo", "integ_req"]
         + [f"sdone{j}" for j in range(n_cols)], n_pass=n_pass, t_req=t_req, t_sync=T_SYNC)

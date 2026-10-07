"""N8 compiler co-design & quality gate.

Default gate (projected, to be replaced by the N8 researcher with a SmolLM2-135M
measurement): per-output compute SNR >= 28 dB (analog/docs/specs.py SNR_T_ATTN_DB,
the attention-class end-to-end target; note 27g3: compute-SNR, not ENOB, is the
accuracy metric) and a format floor of W4A8 (repo contract). No re-quantization,
rotation or fine-tuning is assumed, so no co-design cost is charged.
"""
OPTIONS = {
    "snr28_w4a8": dict(params=dict(snr_target_db=28.0, min_wbits=4, min_abits=8),
                       provenance="specs.SNR_T_ATTN_DB (projected gate, not measured on a model)"),
}
DEFAULT = "snr28_w4a8"
SWEEP = dict(snr_target_db=[24.0, 28.0, 34.0])


def gate(p, acc, fmt):
    margin = acc["snr_db"] - p["snr_target_db"]
    ok = margin >= 0 and fmt["wbits"] >= p["min_wbits"] and fmt["abits"] >= p["min_abits"]
    return dict(passed=bool(ok), target_db=p["snr_target_db"], margin_db=margin)

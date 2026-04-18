pragma circom 2.1.9;
include "tsip_main_v3_base.circom";

component main {public [
    hash_prev,
    hash_curr,
    hash_anchor,
    step_dt_sq,
    tier_vmax_sq,
    tier_anchor_cap_sq,
    cap_policy_sq,
    payload_commitment,
    secret_commitment,
    modeset_commitment,
    mode_tag
]} = TSIPMainV3(30);

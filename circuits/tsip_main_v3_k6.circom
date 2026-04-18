pragma circom 2.1.9;
include "tsip_main_v3_base.circom";

// Public signal order (runtime verifier must align):
// [0] hash_prev
// [1] hash_curr
// [2] hash_anchor
// [3] step_dt_sq
// [4] tier_vmax_sq
// [5] tier_anchor_cap_sq
// [6] cap_policy_sq
// [7] payload_commitment
// [8] secret_commitment
// [9] modeset_commitment
// [10] mode_tag
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
]} = TSIPMainV3(6);

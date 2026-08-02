pragma circom 2.1.9;
include "tsip_main_v4_paper_base.circom";

component main {public [
    hash_prev,
    hash_curr,
    hash_anchor,
    step_dt_sq,
    tier_vmax_sq,
    tier_anchor_cap_sq,
    cap_policy_sq,
    primary_commitment,
    payload_commitment_v2,
    share_content_commitment_a,
    share_content_commitment_r,
    context_commitment,
    blob_hash,
    package_digest_a,
    package_digest_r,
    fingerprint_challenge,
    secret_commitment,
    modeset_commitment,
    mode_tag
]} = TSIPMainV4Paper(6);

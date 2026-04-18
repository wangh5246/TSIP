pragma circom 2.1.9;

include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/bitify.circom";

// TSIP v3 base template.
// K is compile-time constant via wrapper circuits (k6/k30 artifacts).
//
// Enforced constraints (explicit):
//   C1  Poseidon(x1, y1)      == hash_prev
//   C2  Poseidon(x2, y2)      == hash_curr
//   C3  Poseidon(x_anchor,y_anchor) == hash_anchor
//   C4  dist_sq <= tier_vmax_sq * step_dt_sq
//   C5  dist_sq <= mode_vmax_sq(selected_m) * step_dt_sq
//   C6  Poseidon(payload_lo, payload_hi) == payload_commitment
//   C7  Poseidon(secret, user_id_field)  == secret_commitment
//   C8  Poseidon(modeset_bitmap, modeset_salt) == modeset_commitment
//   C9  modeset_bitmap[selected_m] == 1
//   C10 Poseidon(mode_id, secret) == mode_tag
//   C11 anchor_dist_sq <= tier_anchor_cap_sq
//   C12 anchor_dist_sq <= cap_policy_sq
//   C13 anchor_dist_sq <= mode_anchor_cap_sq(selected_m)
//   C14 cap_policy_sq <= tier_anchor_cap_sq
//   C15 tier_anchor_cap_sq == K^2 * tier_vmax_sq * step_dt_sq
//   C16 mode_vmax_sq(selected_m) <= tier_vmax_sq

template PoseidonHash2() {
    signal input a;
    signal input b;
    signal output out;

    component h = Poseidon(2);
    h.inputs[0] <== a;
    h.inputs[1] <== b;
    out <== h.out;
}

template TSIPMainV3(K_WINDOW) {
    var K2 = K_WINDOW * K_WINDOW;

    // Private location witnesses.
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    signal input x_anchor;
    signal input y_anchor;

    // Public commitments and caps.
    signal input hash_prev;
    signal input hash_curr;
    signal input hash_anchor;
    signal input step_dt_sq;
    signal input tier_vmax_sq;
    signal input tier_anchor_cap_sq;
    signal input cap_policy_sq;

    // Payload binding (P4).
    signal input payload_lo;
    signal input payload_hi;
    signal input payload_commitment;

    // Secret binding (P5).
    signal input secret;
    signal input user_id_field;
    signal input secret_commitment;

    // Hidden mode-membership witnesses and disclosures.
    signal input modeset_bitmap;
    signal input modeset_salt;
    signal input mode_s0;
    signal input mode_s1;
    signal input mode_s2;
    signal input mode_s3;
    signal input modeset_commitment;
    signal input mode_tag;

    // C1/C2/C3 hash bindings.
    component prevHash = PoseidonHash2();
    prevHash.a <== x1;
    prevHash.b <== y1;
    prevHash.out === hash_prev;

    component currHash = PoseidonHash2();
    currHash.a <== x2;
    currHash.b <== y2;
    currHash.out === hash_curr;

    component anchorHash = PoseidonHash2();
    anchorHash.a <== x_anchor;
    anchorHash.b <== y_anchor;
    anchorHash.out === hash_anchor;

    // Distance squares.
    signal dx;
    signal dy;
    signal dx_sq;
    signal dy_sq;
    signal dist_sq;
    dx <== x2 - x1;
    dy <== y2 - y1;
    dx_sq <== dx * dx;
    dy_sq <== dy * dy;
    dist_sq <== dx_sq + dy_sq;

    signal dax;
    signal day;
    signal dax_sq;
    signal day_sq;
    signal anchor_dist_sq;
    dax <== x2 - x_anchor;
    day <== y2 - y_anchor;
    dax_sq <== dax * dax;
    day_sq <== day * day;
    anchor_dist_sq <== dax_sq + day_sq;

    // Coordinate range checks.
    component rangeX1 = LessThan(32);
    component rangeY1 = LessThan(32);
    component rangeX2 = LessThan(32);
    component rangeY2 = LessThan(32);
    component rangeXA = LessThan(32);
    component rangeYA = LessThan(32);

    rangeX1.in[0] <== x1; rangeX1.in[1] <== 1000000; rangeX1.out === 1;
    rangeY1.in[0] <== y1; rangeY1.in[1] <== 1000000; rangeY1.out === 1;
    rangeX2.in[0] <== x2; rangeX2.in[1] <== 1000000; rangeX2.out === 1;
    rangeY2.in[0] <== y2; rangeY2.in[1] <== 1000000; rangeY2.out === 1;
    rangeXA.in[0] <== x_anchor; rangeXA.in[1] <== 1000000; rangeXA.out === 1;
    rangeYA.in[0] <== y_anchor; rangeYA.in[1] <== 1000000; rangeYA.out === 1;

    // C6 payload binding.
    component payloadHash = PoseidonHash2();
    payloadHash.a <== payload_lo;
    payloadHash.b <== payload_hi;
    payloadHash.out === payload_commitment;

    // C7 secret binding.
    component secretHash = PoseidonHash2();
    secretHash.a <== secret;
    secretHash.b <== user_id_field;
    secretHash.out === secret_commitment;

    // Mode selector one-hot constraints.
    mode_s0 * (mode_s0 - 1) === 0;
    mode_s1 * (mode_s1 - 1) === 0;
    mode_s2 * (mode_s2 - 1) === 0;
    mode_s3 * (mode_s3 - 1) === 0;

    signal mode_sum;
    mode_sum <== mode_s0 + mode_s1 + mode_s2 + mode_s3;
    mode_sum === 1;

    signal mode_id;
    mode_id <== mode_s1 + 2 * mode_s2 + 3 * mode_s3;

    signal mode_vmax_sq;
    // walk=3,bike=10,vehicle=33,transit=40 (m/s)
    // squares: 9,100,1089,1600
    mode_vmax_sq <== 9 * mode_s0 + 100 * mode_s1 + 1089 * mode_s2 + 1600 * mode_s3;

    // C8/C9: modeset commitment + membership.
    component bitmapBits = Num2Bits(4);
    bitmapBits.in <== modeset_bitmap;

    component modesetHash = PoseidonHash2();
    modesetHash.a <== modeset_bitmap;
    modesetHash.b <== modeset_salt;
    modesetHash.out === modeset_commitment;

    signal selected_in_set_0;
    signal selected_in_set_1;
    signal selected_in_set_2;
    signal selected_in_set_3;
    signal selected_in_set;
    selected_in_set_0 <== bitmapBits.out[0] * mode_s0;
    selected_in_set_1 <== bitmapBits.out[1] * mode_s1;
    selected_in_set_2 <== bitmapBits.out[2] * mode_s2;
    selected_in_set_3 <== bitmapBits.out[3] * mode_s3;
    selected_in_set <== selected_in_set_0 + selected_in_set_1 + selected_in_set_2 + selected_in_set_3;
    selected_in_set === 1;

    // C10: hidden mode disclosure tag.
    component modeTagHash = PoseidonHash2();
    modeTagHash.a <== mode_id;
    modeTagHash.b <== secret;
    modeTagHash.out === mode_tag;

    // C4/C5 per-step bounds.
    signal tier_step_cap_sq;
    signal mode_step_cap_sq;
    tier_step_cap_sq <== tier_vmax_sq * step_dt_sq;
    mode_step_cap_sq <== mode_vmax_sq * step_dt_sq;

    component stepTierLE = LessEqThan(64);
    stepTierLE.in[0] <== dist_sq;
    stepTierLE.in[1] <== tier_step_cap_sq;
    stepTierLE.out === 1;

    component stepModeLE = LessEqThan(64);
    stepModeLE.in[0] <== dist_sq;
    stepModeLE.in[1] <== mode_step_cap_sq;
    stepModeLE.out === 1;

    // C15: tier anchor cap formula.
    signal tier_anchor_expected_sq;
    tier_anchor_expected_sq <== tier_vmax_sq * step_dt_sq * K2;
    tier_anchor_expected_sq === tier_anchor_cap_sq;

    // Mode anchor cap (derived in-circuit).
    signal mode_anchor_cap_sq;
    mode_anchor_cap_sq <== mode_vmax_sq * step_dt_sq * K2;

    // C11/C12/C13 anchor constraints.
    component anchorTierLE = LessEqThan(64);
    anchorTierLE.in[0] <== anchor_dist_sq;
    anchorTierLE.in[1] <== tier_anchor_cap_sq;
    anchorTierLE.out === 1;

    component anchorPolicyLE = LessEqThan(64);
    anchorPolicyLE.in[0] <== anchor_dist_sq;
    anchorPolicyLE.in[1] <== cap_policy_sq;
    anchorPolicyLE.out === 1;

    component anchorModeLE = LessEqThan(64);
    anchorModeLE.in[0] <== anchor_dist_sq;
    anchorModeLE.in[1] <== mode_anchor_cap_sq;
    anchorModeLE.out === 1;

    // C14: cap_policy_sq <= tier_anchor_cap_sq.
    component policyVsTierLE = LessEqThan(64);
    policyVsTierLE.in[0] <== cap_policy_sq;
    policyVsTierLE.in[1] <== tier_anchor_cap_sq;
    policyVsTierLE.out === 1;

    // C16: selected mode bound cannot exceed enrollment tier bound.
    component modeVsTierLE = LessEqThan(64);
    modeVsTierLE.in[0] <== mode_vmax_sq;
    modeVsTierLE.in[1] <== tier_vmax_sq;
    modeVsTierLE.out === 1;
}

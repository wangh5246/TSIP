pragma circom 2.1.9;

include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/bitify.circom";

// TSIP/SHTPC v4 paper profile with complete Route-B payload binding.
//
// Public signal order is fixed by the wrapper circuits:
// [0]  hash_prev
// [1]  hash_curr
// [2]  hash_anchor
// [3]  step_dt_sq
// [4]  tier_vmax_sq
// [5]  tier_anchor_cap_sq
// [6]  cap_policy_sq
// [7]  primary_commitment
// [8]  payload_commitment_v2
// [9]  share_content_commitment_a
// [10] share_content_commitment_r
// [11] context_commitment
// [12] blob_hash
// [13] package_digest_a
// [14] package_digest_r
// [15] fingerprint_challenge
// [16] secret_commitment
// [17] modeset_commitment
// [18] mode_tag
//
// This profile extends the archived v4 relation:
// - Domain-separated salted location commitments: H_loc(x, y, r).
// - Hidden primary derivation: x/y are decomposed into 100m grid cell + remainder.
// - C21+ binds the actual canonical A/R package digests and fingerprints.
// - The fingerprint sum reconstructs the coordinate-derived one-hot payload.
// - A transport digest binds both package digests and the payload commitment.

template PoseidonHash2() {
    signal input a;
    signal input b;
    signal output out;

    component h = Poseidon(2);
    h.inputs[0] <== a;
    h.inputs[1] <== b;
    out <== h.out;
}

template PoseidonHash3() {
    signal input a;
    signal input b;
    signal input c;
    signal output out;

    component h = Poseidon(3);
    h.inputs[0] <== a;
    h.inputs[1] <== b;
    h.inputs[2] <== c;
    out <== h.out;
}

template PoseidonHash4() {
    signal input a;
    signal input b;
    signal input c;
    signal input d;
    signal output out;

    component h = Poseidon(4);
    h.inputs[0] <== a;
    h.inputs[1] <== b;
    h.inputs[2] <== c;
    h.inputs[3] <== d;
    out <== h.out;
}

template PoseidonChain(N) {
    signal input values[N];
    signal output out;

    component hashes[N - 1];
    for (var i = 0; i < N - 1; i++) {
        hashes[i] = PoseidonHash2();
        if (i == 0) {
            hashes[i].a <== values[0];
        } else {
            hashes[i].a <== hashes[i - 1].out;
        }
        hashes[i].b <== values[i + 1];
    }
    out <== hashes[N - 2].out;
}

template TSIPMainV4Paper(K_WINDOW) {
    var K2 = K_WINDOW * K_WINDOW;
    var CELL_SIZE = 100;
    var GRID_W = 100;
    var PRIMARY_DOMAIN = 10695660883109164895475699623659103561995198970106986990705378483762687899453;
    var LOCATION_DOMAIN = 13438772816005774064980671497565679151312422504895540615973695163839855496153;
    var FINGERPRINT_DOMAIN = 12550785583943332535479939589517079248145774403068194489857104484496462427665;
    var CHANNEL_A_DOMAIN = 8047598694201793237522922787609908033326419603133614504774744427868402019068;
    var CHANNEL_R_DOMAIN = 16086552631809438988362066530905932535663429494623067843956546268045675612948;
    var PAYLOAD_DOMAIN = 11910578474717361302787665509585616222652245192815783002615163087873047856036;
    var BLOB_DOMAIN = 14185315476196531533738136216231547378548400905526471139269979764831854752932;

    // Private location witnesses.
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    signal input x_anchor;
    signal input y_anchor;
    signal input r_prev;
    signal input r_curr;
    signal input r_anchor;

    // Public commitments and caps.
    signal input hash_prev;
    signal input hash_curr;
    signal input hash_anchor;
    signal input step_dt_sq;
    signal input tier_vmax_sq;
    signal input tier_anchor_cap_sq;
    signal input cap_policy_sq;

    // C17-C21 Route-B payload binding.
    signal input payload_cell_x;
    signal input payload_cell_y;
    signal input payload_rem_x;
    signal input payload_rem_y;
    signal input payload_primary_idx;
    signal input primary_salt;
    signal input primary_commitment;
    signal input payload_commitment_v2;
    signal input share_content_commitment_a;
    signal input share_content_commitment_r;
    signal input context_commitment;
    signal input blob_hash;
    signal input package_digest_a;
    signal input package_digest_r;
    signal input fingerprint_challenge;
    signal input fingerprint_a;
    signal input fingerprint_r;
    signal input contribution_bit;

    // Secret binding.
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

    // C1/C2/C3 domain-separated salted location commitment bindings.
    component prevHash = PoseidonChain(4);
    prevHash.values[0] <== LOCATION_DOMAIN;
    prevHash.values[1] <== x1;
    prevHash.values[2] <== y1;
    prevHash.values[3] <== r_prev;
    prevHash.out === hash_prev;

    component currHash = PoseidonChain(4);
    currHash.values[0] <== LOCATION_DOMAIN;
    currHash.values[1] <== x2;
    currHash.values[2] <== y2;
    currHash.values[3] <== r_curr;
    currHash.out === hash_curr;

    component anchorHash = PoseidonChain(4);
    anchorHash.values[0] <== LOCATION_DOMAIN;
    anchorHash.values[1] <== x_anchor;
    anchorHash.values[2] <== y_anchor;
    anchorHash.values[3] <== r_anchor;
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

    // C17-C20: derive primary from current hidden coordinate and canonical grid.
    x2 === payload_cell_x * CELL_SIZE + payload_rem_x;
    y2 === payload_cell_y * CELL_SIZE + payload_rem_y;
    payload_primary_idx === payload_cell_y * GRID_W + payload_cell_x;

    component cellXRange = LessThan(16);
    component cellYRange = LessThan(16);
    component remXRange = LessThan(16);
    component remYRange = LessThan(16);
    cellXRange.in[0] <== payload_cell_x; cellXRange.in[1] <== GRID_W; cellXRange.out === 1;
    cellYRange.in[0] <== payload_cell_y; cellYRange.in[1] <== GRID_W; cellYRange.out === 1;
    remXRange.in[0] <== payload_rem_x; remXRange.in[1] <== CELL_SIZE; remXRange.out === 1;
    remYRange.in[0] <== payload_rem_y; remYRange.in[1] <== CELL_SIZE; remYRange.out === 1;

    // C21+: bind the hidden primary and actual channel-package fingerprints.
    component primaryHash = PoseidonChain(4);
    primaryHash.values[0] <== PRIMARY_DOMAIN;
    primaryHash.values[1] <== context_commitment;
    primaryHash.values[2] <== payload_primary_idx;
    primaryHash.values[3] <== primary_salt;
    primaryHash.out === primary_commitment;

    component challengeHash = PoseidonChain(5);
    challengeHash.values[0] <== FINGERPRINT_DOMAIN;
    challengeHash.values[1] <== context_commitment;
    challengeHash.values[2] <== primary_commitment;
    challengeHash.values[3] <== package_digest_a;
    challengeHash.values[4] <== package_digest_r;
    challengeHash.out === fingerprint_challenge;

    component shareHashA = PoseidonChain(5);
    shareHashA.values[0] <== CHANNEL_A_DOMAIN;
    shareHashA.values[1] <== primary_commitment;
    shareHashA.values[2] <== context_commitment;
    shareHashA.values[3] <== package_digest_a;
    shareHashA.values[4] <== fingerprint_a;
    shareHashA.out === share_content_commitment_a;

    component shareHashR = PoseidonChain(5);
    shareHashR.values[0] <== CHANNEL_R_DOMAIN;
    shareHashR.values[1] <== primary_commitment;
    shareHashR.values[2] <== context_commitment;
    shareHashR.values[3] <== package_digest_r;
    shareHashR.values[4] <== fingerprint_r;
    shareHashR.out === share_content_commitment_r;

    contribution_bit * (contribution_bit - 1) === 0;

    component primaryBits = Num2Bits(14);
    primaryBits.in <== payload_primary_idx;
    signal alphaPower[14];
    signal selectedPower[14];
    signal fingerprintPower[15];
    alphaPower[0] <== fingerprint_challenge;
    fingerprintPower[0] <== 1;
    for (var fp_i = 0; fp_i < 14; fp_i++) {
        selectedPower[fp_i] <== 1 + primaryBits.out[fp_i] * (alphaPower[fp_i] - 1);
        fingerprintPower[fp_i + 1] <== fingerprintPower[fp_i] * selectedPower[fp_i];
        if (fp_i < 13) {
            alphaPower[fp_i + 1] <== alphaPower[fp_i] * alphaPower[fp_i];
        }
    }
    fingerprint_a + fingerprint_r === contribution_bit * fingerprintPower[14];

    component payloadHash = PoseidonChain(6);
    payloadHash.values[0] <== PAYLOAD_DOMAIN;
    payloadHash.values[1] <== context_commitment;
    payloadHash.values[2] <== primary_commitment;
    payloadHash.values[3] <== share_content_commitment_a;
    payloadHash.values[4] <== share_content_commitment_r;
    payloadHash.values[5] <== contribution_bit;
    payloadHash.out === payload_commitment_v2;

    component transportHash = PoseidonChain(5);
    transportHash.values[0] <== BLOB_DOMAIN;
    transportHash.values[1] <== context_commitment;
    transportHash.values[2] <== package_digest_a;
    transportHash.values[3] <== package_digest_r;
    transportHash.values[4] <== payload_commitment_v2;
    transportHash.out === blob_hash;

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

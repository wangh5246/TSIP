pragma circom 2.1.9;

include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/bitify.circom";

// Settlement v5 period circuit.
// C1-C5 keep continuity, C11-C16 keep ADWC, C17-C20 bind grid cells to
// tariff zones, C21 binds odometer deltas plus fallback to the fee, and C22
// caps every odometer delta by the same tier speed budget used for geometry.

template RangeSigned24() {
    signal input in;
    signal shifted;
    shifted <== in + 8388608;
    component bits = Num2Bits(24);
    bits.in <== shifted;
}

template RangeSignedDiff25() {
    signal input in;
    signal shifted;
    shifted <== in + 16777216;
    component bits = Num2Bits(25);
    bits.in <== shifted;
}

template PoseidonHash2() {
    signal input a;
    signal input b;
    signal output out;
    component h = Poseidon(2);
    h.inputs[0] <== a;
    h.inputs[1] <== b;
    out <== h.out;
}

template PoseidonChain4() {
    signal input in[4];
    signal output out;
    component h[4];
    h[0] = PoseidonHash2();
    h[0].a <== 0;
    h[0].b <== in[0];
    for (var i = 1; i < 4; i++) {
        h[i] = PoseidonHash2();
        h[i].a <== h[i - 1].out;
        h[i].b <== in[i];
    }
    out <== h[3].out;
}

template PoseidonChain7() {
    signal input in[7];
    signal output out;
    component h[7];
    h[0] = PoseidonHash2();
    h[0].a <== 0;
    h[0].b <== in[0];
    for (var i = 1; i < 7; i++) {
        h[i] = PoseidonHash2();
        h[i].a <== h[i - 1].out;
        h[i].b <== in[i];
    }
    out <== h[6].out;
}

template PoseidonChain8() {
    signal input in[8];
    signal output out;
    component h[8];
    h[0] = PoseidonHash2();
    h[0].a <== 0;
    h[0].b <== in[0];
    for (var i = 1; i < 8; i++) {
        h[i] = PoseidonHash2();
        h[i].a <== h[i - 1].out;
        h[i].b <== in[i];
    }
    out <== h[7].out;
}

template SettlementPeriodV5(N_FIXES, TREE_DEPTH, K_WINDOW) {
    var CELL_SIZE = 100;
    var GRID_W = 100;
    var K2 = K_WINDOW * K_WINDOW;

    signal input receiver_fix_root;
    signal input tariff_root;
    signal input interval_commitment_root;
    signal input period_id_field;
    signal input tariff_version;
    signal input device_attestation_commitment;
    signal input total_fee_cents;
    signal input total_distance_m;
    signal input fallback_intervals;
    signal input cadence_sec;
    signal input tier_vmax_mps;
    signal input tier_vmax_sq;
    signal input mode_vmax_sq;
    signal input cap_policy_sq;
    signal input max_zone_rate_cents_per_m;
    signal input max_dt_sec;
    signal input period_start_time;
    signal input period_end_time;
    signal input month_id;
    signal input month_start_time;
    signal input month_end_time;

    signal input x[N_FIXES];
    signal input y[N_FIXES];
    signal input loc_salt[N_FIXES];
    signal input auth_time[N_FIXES];
    signal input odometer_m[N_FIXES];
    signal input fix_nonce_field[N_FIXES];
    signal input fix_cell_x[N_FIXES];
    signal input fix_cell_y[N_FIXES];

    signal input payload_cell_x[N_FIXES - 1];
    signal input payload_cell_y[N_FIXES - 1];
    signal input payload_rem_x[N_FIXES - 1];
    signal input payload_rem_y[N_FIXES - 1];
    signal input payload_cell_idx[N_FIXES - 1];
    signal input zone_id[N_FIXES - 1];
    signal input zone_rate_cents_per_m[N_FIXES - 1];
    signal input zone_path_sibling[N_FIXES - 1][TREE_DEPTH];
    signal input zone_path_is_right[N_FIXES - 1][TREE_DEPTH];

    signal dt[N_FIXES - 1];
    signal dt_sq[N_FIXES - 1];
    signal odo_delta[N_FIXES - 1];
    signal dx[N_FIXES - 1];
    signal dy[N_FIXES - 1];
    signal dx_sq[N_FIXES - 1];
    signal dy_sq[N_FIXES - 1];
    signal dist_sq[N_FIXES - 1];
    signal dax[N_FIXES - 1];
    signal day[N_FIXES - 1];
    signal dax_sq[N_FIXES - 1];
    signal day_sq[N_FIXES - 1];
    signal anchor_dist_sq[N_FIXES - 1];
    signal odo_step_cap_m[N_FIXES - 1];
    signal tier_step_cap_sq[N_FIXES - 1];
    signal mode_step_cap_sq[N_FIXES - 1];
    signal mode_anchor_cap_sq[N_FIXES - 1];
    signal tier_anchor_expected_sq[N_FIXES - 1];
    signal normal_fee[N_FIXES - 1];
    signal fallback_distance_m[N_FIXES - 1];
    signal fallback_fee[N_FIXES - 1];
    signal fallback_flag[N_FIXES - 1];
    signal cadence_ok[N_FIXES - 1];
    signal selected_normal_fee[N_FIXES - 1];
    signal selected_fallback_fee[N_FIXES - 1];
    signal fee_terms[N_FIXES - 1];
    signal zone_acc[N_FIXES - 1][TREE_DEPTH + 1];
    signal zone_left_from_acc[N_FIXES - 1][TREE_DEPTH];
    signal zone_left_from_sib[N_FIXES - 1][TREE_DEPTH];
    signal zone_right_from_sib[N_FIXES - 1][TREE_DEPTH];
    signal zone_right_from_acc[N_FIXES - 1][TREE_DEPTH];
    signal zone_left[N_FIXES - 1][TREE_DEPTH];
    signal zone_right[N_FIXES - 1][TREE_DEPTH];
    signal fee_sum[N_FIXES];
    signal distance_sum[N_FIXES];
    signal fallback_sum[N_FIXES];

    component locHash[N_FIXES];
    component fixCommit[N_FIXES];
    component fixRootStep[N_FIXES];
    component rangeX[N_FIXES];
    component rangeY[N_FIXES];
    component rangeOdo[N_FIXES];
    component rangeTime[N_FIXES];
    component rangeCellX[N_FIXES];
    component rangeCellY[N_FIXES];

    component dtRange[N_FIXES - 1];
    component dtMaxLE[N_FIXES - 1];
    component odoDeltaRange[N_FIXES - 1];
    component rangeDX[N_FIXES - 1];
    component rangeDY[N_FIXES - 1];
    component rangeDAX[N_FIXES - 1];
    component rangeDAY[N_FIXES - 1];
    component stepTierLE[N_FIXES - 1];
    component stepModeLE[N_FIXES - 1];
    component capTierRange[N_FIXES - 1];
    component capModeRange[N_FIXES - 1];
    component distSqRange[N_FIXES - 1];
    component odoTierLE[N_FIXES - 1];
    component anchorTierLE[N_FIXES - 1];
    component anchorPolicyLE[N_FIXES - 1];
    component anchorModeLE[N_FIXES - 1];
    component policyVsTierLE[N_FIXES - 1];
    component modeVsTierLE[N_FIXES - 1];
    component cellXRange[N_FIXES - 1];
    component cellYRange[N_FIXES - 1];
    component remXRange[N_FIXES - 1];
    component remYRange[N_FIXES - 1];
    component zoneLeaf[N_FIXES - 1];
    component zonePathHash[N_FIXES - 1][TREE_DEPTH];
    component cadenceLE[N_FIXES - 1];
    component intervalCommit[N_FIXES - 1];
    component intervalRootStep[N_FIXES - 1];
    component totalFeeRange;
    component totalDistanceRange;
    component tierVmaxMpsRange;
    component spanRange;
    component spanMaxLE;
    component spanPositive;
    component monthLowLE;
    component monthHighLT;

    for (var i = 0; i < N_FIXES; i++) {
        locHash[i] = PoseidonChain4();
        locHash[i].in[0] <== x[i];
        locHash[i].in[1] <== y[i];
        locHash[i].in[2] <== loc_salt[i];
        locHash[i].in[3] <== period_id_field;

        fixCommit[i] = PoseidonChain8();
        fixCommit[i].in[0] <== device_attestation_commitment;
        fixCommit[i].in[1] <== period_id_field;
        fixCommit[i].in[2] <== i;
        fixCommit[i].in[3] <== auth_time[i];
        fixCommit[i].in[4] <== fix_cell_x[i];
        fixCommit[i].in[5] <== fix_cell_y[i];
        fixCommit[i].in[6] <== odometer_m[i];
        fixCommit[i].in[7] <== fix_nonce_field[i];

        rangeX[i] = RangeSigned24();
        rangeY[i] = RangeSigned24();
        rangeOdo[i] = Num2Bits(64);
        rangeTime[i] = Num2Bits(48);
        rangeCellX[i] = LessThan(32);
        rangeCellY[i] = LessThan(32);
        rangeX[i].in <== x[i];
        rangeY[i].in <== y[i];
        rangeOdo[i].in <== odometer_m[i];
        rangeTime[i].in <== auth_time[i];
        rangeCellX[i].in[0] <== fix_cell_x[i];
        rangeCellX[i].in[1] <== GRID_W;
        rangeCellX[i].out === 1;
        rangeCellY[i].in[0] <== fix_cell_y[i];
        rangeCellY[i].in[1] <== GRID_W;
        rangeCellY[i].out === 1;

        fixRootStep[i] = PoseidonHash2();
        if (i == 0) {
            fixRootStep[i].a <== 0;
        } else {
            fixRootStep[i].a <== fixRootStep[i - 1].out;
        }
        fixRootStep[i].b <== fixCommit[i].out;
    }
    fixRootStep[N_FIXES - 1].out === receiver_fix_root;

    tierVmaxMpsRange = Num2Bits(16);
    tierVmaxMpsRange.in <== tier_vmax_mps;
    tier_vmax_sq === tier_vmax_mps * tier_vmax_mps;

    for (var i = 0; i < N_FIXES - 1; i++) {
        dt[i] <== auth_time[i + 1] - auth_time[i];
        dt_sq[i] <== dt[i] * dt[i];
        odo_delta[i] <== odometer_m[i + 1] - odometer_m[i];

        // dt now bounded by max_dt_sec (<= 600), so dt fits in <=10 bits.
        // Keep a generous 16-bit range proof; the hard cap is the real bound.
        dtRange[i] = Num2Bits(16);
        odoDeltaRange[i] = Num2Bits(64);
        dtRange[i].in <== dt[i];
        odoDeltaRange[i].in <== odo_delta[i];

        // HARD upper bound on dt: closes the "large-dt relaxes continuity" attack.
        dtMaxLE[i] = LessEqThan(16);
        dtMaxLE[i].in[0] <== dt[i];
        dtMaxLE[i].in[1] <== max_dt_sec;
        dtMaxLE[i].out === 1;

        dx[i] <== x[i + 1] - x[i];
        dy[i] <== y[i + 1] - y[i];
        dx_sq[i] <== dx[i] * dx[i];
        dy_sq[i] <== dy[i] * dy[i];
        dist_sq[i] <== dx_sq[i] + dy_sq[i];

        rangeDX[i] = RangeSignedDiff25();
        rangeDY[i] = RangeSignedDiff25();
        rangeDX[i].in <== dx[i];
        rangeDY[i].in <== dy[i];

        odo_step_cap_m[i] <== tier_vmax_mps * dt[i];
        tier_step_cap_sq[i] <== tier_vmax_sq * dt_sq[i];
        mode_step_cap_sq[i] <== mode_vmax_sq * dt_sq[i];

        odoTierLE[i] = LessEqThan(64);
        odoTierLE[i].in[0] <== odo_delta[i];
        odoTierLE[i].in[1] <== odo_step_cap_m[i];
        odoTierLE[i].out === 1;

        // dt is now hard-capped, so cap_sq <= 2^52. Assert operands explicitly
        // so soundness no longer silently depends on an unstated dt bound.
        capTierRange[i] = Num2Bits(52);
        capTierRange[i].in <== tier_step_cap_sq[i];
        capModeRange[i] = Num2Bits(52);
        capModeRange[i].in <== mode_step_cap_sq[i];
        distSqRange[i] = Num2Bits(52);
        distSqRange[i].in <== dist_sq[i];

        stepTierLE[i] = LessEqThan(52);
        stepTierLE[i].in[0] <== dist_sq[i];
        stepTierLE[i].in[1] <== tier_step_cap_sq[i];
        stepTierLE[i].out === 1;

        stepModeLE[i] = LessEqThan(52);
        stepModeLE[i].in[0] <== dist_sq[i];
        stepModeLE[i].in[1] <== mode_step_cap_sq[i];
        stepModeLE[i].out === 1;

        var anchor_i = 0;
        if (i + 1 >= K_WINDOW) {
            anchor_i = i + 1 - K_WINDOW;
        }
        dax[i] <== x[i + 1] - x[anchor_i];
        day[i] <== y[i + 1] - y[anchor_i];
        dax_sq[i] <== dax[i] * dax[i];
        day_sq[i] <== day[i] * day[i];
        anchor_dist_sq[i] <== dax_sq[i] + day_sq[i];

        rangeDAX[i] = RangeSignedDiff25();
        rangeDAY[i] = RangeSignedDiff25();
        rangeDAX[i].in <== dax[i];
        rangeDAY[i].in <== day[i];

        tier_anchor_expected_sq[i] <== tier_vmax_sq * dt_sq[i] * K2;
        mode_anchor_cap_sq[i] <== mode_vmax_sq * dt_sq[i] * K2;

        anchorTierLE[i] = LessEqThan(80);
        anchorTierLE[i].in[0] <== anchor_dist_sq[i];
        anchorTierLE[i].in[1] <== tier_anchor_expected_sq[i];
        anchorTierLE[i].out === 1;

        anchorPolicyLE[i] = LessEqThan(80);
        anchorPolicyLE[i].in[0] <== anchor_dist_sq[i];
        anchorPolicyLE[i].in[1] <== cap_policy_sq;
        anchorPolicyLE[i].out === 1;

        anchorModeLE[i] = LessEqThan(80);
        anchorModeLE[i].in[0] <== anchor_dist_sq[i];
        anchorModeLE[i].in[1] <== mode_anchor_cap_sq[i];
        anchorModeLE[i].out === 1;

        policyVsTierLE[i] = LessEqThan(80);
        policyVsTierLE[i].in[0] <== cap_policy_sq;
        policyVsTierLE[i].in[1] <== tier_anchor_expected_sq[i];
        policyVsTierLE[i].out === 1;

        modeVsTierLE[i] = LessEqThan(80);
        modeVsTierLE[i].in[0] <== mode_vmax_sq;
        modeVsTierLE[i].in[1] <== tier_vmax_sq;
        modeVsTierLE[i].out === 1;

        x[i] === payload_cell_x[i] * CELL_SIZE + payload_rem_x[i];
        y[i] === payload_cell_y[i] * CELL_SIZE + payload_rem_y[i];
        payload_cell_x[i] === fix_cell_x[i];
        payload_cell_y[i] === fix_cell_y[i];
        payload_cell_idx[i] === payload_cell_y[i] * GRID_W + payload_cell_x[i];

        cellXRange[i] = LessThan(32);
        cellYRange[i] = LessThan(32);
        remXRange[i] = LessThan(32);
        remYRange[i] = LessThan(32);
        cellXRange[i].in[0] <== payload_cell_x[i];
        cellXRange[i].in[1] <== GRID_W;
        cellXRange[i].out === 1;
        cellYRange[i].in[0] <== payload_cell_y[i];
        cellYRange[i].in[1] <== GRID_W;
        cellYRange[i].out === 1;
        remXRange[i].in[0] <== payload_rem_x[i];
        remXRange[i].in[1] <== CELL_SIZE;
        remXRange[i].out === 1;
        remYRange[i].in[0] <== payload_rem_y[i];
        remYRange[i].in[1] <== CELL_SIZE;
        remYRange[i].out === 1;

        zoneLeaf[i] = PoseidonChain4();
        zoneLeaf[i].in[0] <== tariff_version;
        zoneLeaf[i].in[1] <== payload_cell_idx[i];
        zoneLeaf[i].in[2] <== zone_id[i];
        zoneLeaf[i].in[3] <== zone_rate_cents_per_m[i];
        zone_acc[i][0] <== zoneLeaf[i].out;

        for (var j = 0; j < TREE_DEPTH; j++) {
            zone_path_is_right[i][j] * (zone_path_is_right[i][j] - 1) === 0;
            zone_left_from_acc[i][j] <== zone_acc[i][j] * (1 - zone_path_is_right[i][j]);
            zone_left_from_sib[i][j] <== zone_path_sibling[i][j] * zone_path_is_right[i][j];
            zone_right_from_sib[i][j] <== zone_path_sibling[i][j] * (1 - zone_path_is_right[i][j]);
            zone_right_from_acc[i][j] <== zone_acc[i][j] * zone_path_is_right[i][j];
            zone_left[i][j] <== zone_left_from_acc[i][j] + zone_left_from_sib[i][j];
            zone_right[i][j] <== zone_right_from_sib[i][j] + zone_right_from_acc[i][j];
            zonePathHash[i][j] = PoseidonHash2();
            zonePathHash[i][j].a <== zone_left[i][j];
            zonePathHash[i][j].b <== zone_right[i][j];
            zone_acc[i][j + 1] <== zonePathHash[i][j].out;
        }
        zone_acc[i][TREE_DEPTH] === tariff_root;

        cadenceLE[i] = LessEqThan(48);
        cadenceLE[i].in[0] <== dt[i];
        cadenceLE[i].in[1] <== cadence_sec;
        cadence_ok[i] <== cadenceLE[i].out;
        fallback_flag[i] <== 1 - cadence_ok[i];

        normal_fee[i] <== odo_delta[i] * zone_rate_cents_per_m[i];
        fallback_distance_m[i] <== dt[i] * tier_vmax_mps;
        fallback_fee[i] <== fallback_distance_m[i] * max_zone_rate_cents_per_m;
        selected_normal_fee[i] <== normal_fee[i] * cadence_ok[i];
        selected_fallback_fee[i] <== fallback_fee[i] * fallback_flag[i];
        fee_terms[i] <== selected_normal_fee[i] + selected_fallback_fee[i];

        intervalCommit[i] = PoseidonChain7();
        intervalCommit[i].in[0] <== fixCommit[i].out;
        intervalCommit[i].in[1] <== fixCommit[i + 1].out;
        intervalCommit[i].in[2] <== odo_delta[i];
        intervalCommit[i].in[3] <== zone_id[i];
        intervalCommit[i].in[4] <== zone_rate_cents_per_m[i];
        intervalCommit[i].in[5] <== fee_terms[i];
        intervalCommit[i].in[6] <== fallback_flag[i];

        intervalRootStep[i] = PoseidonHash2();
        if (i == 0) {
            intervalRootStep[i].a <== 0;
        } else {
            intervalRootStep[i].a <== intervalRootStep[i - 1].out;
        }
        intervalRootStep[i].b <== intervalCommit[i].out;
    }

    // The terminal fix has no outgoing tariff payload, but its signed cell
    // still must bind the endpoint used by the cross-period continuity check.
    x[N_FIXES - 1] === fix_cell_x[N_FIXES - 1] * CELL_SIZE;
    y[N_FIXES - 1] === fix_cell_y[N_FIXES - 1] * CELL_SIZE;

    intervalRootStep[N_FIXES - 2].out === interval_commitment_root;

    // First/last auth_time must equal the declared public window.
    period_start_time === auth_time[0];
    period_end_time === auth_time[N_FIXES - 1];

    // Period length is positive and bounded by PERIOD_MAX (4h = 14400s).
    signal period_span;
    period_span <== period_end_time - period_start_time;
    spanRange = Num2Bits(16);
    spanRange.in <== period_span;
    spanMaxLE = LessEqThan(16);
    spanMaxLE.in[0] <== period_span;
    spanMaxLE.in[1] <== 14400;
    spanMaxLE.out === 1;
    spanPositive = LessThan(16);
    spanPositive.in[0] <== 0;
    spanPositive.in[1] <== period_span;
    spanPositive.out === 1;

    // The verifier supplies canonical month bounds keyed by public month_id.
    // The charger checks that lookup; the circuit checks the half-open window.
    monthLowLE = LessEqThan(48);
    monthLowLE.in[0] <== month_start_time;
    monthLowLE.in[1] <== period_start_time;
    monthLowLE.out === 1;
    monthHighLT = LessThan(48);
    monthHighLT.in[0] <== period_start_time;
    monthHighLT.in[1] <== month_end_time;
    monthHighLT.out === 1;

    fee_sum[0] <== 0;
    distance_sum[0] <== 0;
    fallback_sum[0] <== 0;
    for (var i = 0; i < N_FIXES - 1; i++) {
        fee_sum[i + 1] <== fee_sum[i] + fee_terms[i];
        distance_sum[i + 1] <== distance_sum[i] + odo_delta[i];
        fallback_sum[i + 1] <== fallback_sum[i] + fallback_flag[i];
    }
    fee_sum[N_FIXES - 1] === total_fee_cents;
    distance_sum[N_FIXES - 1] === total_distance_m;
    fallback_sum[N_FIXES - 1] === fallback_intervals;

    totalFeeRange = Num2Bits(96);
    totalDistanceRange = Num2Bits(64);
    totalFeeRange.in <== total_fee_cents;
    totalDistanceRange.in <== total_distance_m;

    // device_attestation_commitment is bound into every fixCommit[i].in[0],
    // so it is constrained by the receiver_fix_root equality above.
}

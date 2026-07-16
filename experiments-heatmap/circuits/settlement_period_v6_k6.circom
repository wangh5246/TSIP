pragma circom 2.1.9;
include "settlement_period_v6_base.circom";

// Public signal order:
// [0]  receiver_fix_root
// [1]  tariff_root
// [2]  interval_commitment_root
// [3]  policy_profile_commitment
// [4]  period_id_field
// [5]  tariff_version
// [6]  device_attestation_commitment
// [7]  total_fee_cents
// [8]  total_distance_m
// [9]  fallback_intervals
// [10] cadence_sec
// [11] tier_vmax_mps
// [12] tier_vmax_sq
// [13] mode_vmax_sq
// [14] cap_policy_sq
// [15] max_zone_rate_cents_per_m
// [16] max_dt_sec
// [17] period_start_time
// [18] period_end_time
// [19] month_id
// [20] month_start_time
// [21] month_end_time
//
// V6 odometer-backed RUC prototype profile:
// - 25 signed fixes = 24 intervals
// - 5 minute cadence = up to 2 hours per period proof
// - monthly bills aggregate accepted period proofs at the charger
component main {public [
    receiver_fix_root,
    tariff_root,
    interval_commitment_root,
    policy_profile_commitment,
    period_id_field,
    tariff_version,
    device_attestation_commitment,
    total_fee_cents,
    total_distance_m,
    fallback_intervals,
    cadence_sec,
    tier_vmax_mps,
    tier_vmax_sq,
    mode_vmax_sq,
    cap_policy_sq,
    max_zone_rate_cents_per_m,
    max_dt_sec,
    period_start_time,
    period_end_time,
    month_id,
    month_start_time,
    month_end_time
]} = SettlementPeriodV6(25, 8, 6);

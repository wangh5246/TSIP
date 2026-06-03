pragma circom 2.1.9;
include "settlement_period_v5_base.circom";

// Public signal order:
// [0]  receiver_fix_root
// [1]  tariff_root
// [2]  interval_commitment_root
// [3]  period_id_field
// [4]  tariff_version
// [5]  device_attestation_commitment
// [6]  total_fee_cents
// [7]  total_distance_m
// [8]  fallback_intervals
// [9]  cadence_sec
// [10] tier_vmax_mps
// [11] tier_vmax_sq
// [12] mode_vmax_sq
// [13] cap_policy_sq
// [14] max_zone_rate_cents_per_m
//
// Core RUC prototype profile:
// - 25 signed fixes = 24 intervals
// - 5 minute cadence = up to 2 hours per period proof
// - monthly bills aggregate accepted period proofs at the charger
component main {public [
    receiver_fix_root,
    tariff_root,
    interval_commitment_root,
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
    max_zone_rate_cents_per_m
]} = SettlementPeriodV5(25, 8, 6);

pragma circom 2.1.9;
include "../experiments-heatmap/circuits/settlement_period_v5_base.circom";

// Public signal order is frozen by common.settlement.PUBLIC_SIGNAL_ORDER.
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
    max_zone_rate_cents_per_m,
    max_dt_sec,
    period_start_time,
    period_end_time,
    month_id,
    month_start_time,
    month_end_time
]} = SettlementPeriodV5(25, 8, 6);

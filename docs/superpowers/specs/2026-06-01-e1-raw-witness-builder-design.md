# E1 Raw Witness Builder Design

## Scope

This change prepares the E1 circuit cross-check without invoking `snarkjs`.
It fixes adversarial trajectory generation and adds reusable witness-input
builders. The subprocess witness gate remains a follow-up change.

## E1 Fast-Path Contract

`adversary_min_fee()` may return honest fixes immediately only for the exact
`all_on` case without explicit relay candidate sets.

Any ablation must preserve its attack-generation semantics:

- `no_odometer` returns a parked zero-distance claim.
- `no_continuity` must reach the existing relaxed construction or RCSPP path.
- `no_max_dt` must reach RCSPP instead of returning honest fixes.
- `no_cadence` must reach RCSPP so later fallback-specific checks receive the
  actual skipped-fix trajectory.

## Builder Boundaries

`build_input_for_fixes()` is the validated fixture path. It accepts explicit
fixes, tariff, and harness parameters. It builds the circuit input and
submission metadata, then optionally runs charger-style submission
verification. Existing `build_input()` delegates to it so the current fixture
remains behaviorally unchanged.

`build_raw_witness_input_for_fixes()` is the E1 circuit-gate path. It:

- builds circuit input directly from supplied fixes;
- ignores receiver signatures because signatures are not inputs to the Circom
  `fixCommit`;
- derives the month window from the first authenticated timestamp;
- uses zero payload remainders by default, documenting the E1 cell-level
  abstraction;
- computes public totals and commitment roots without rejecting deliberately
  invalid `max_dt` trajectories in Python.

The raw builder is not a charger submission validator and must not call
`verify_period_submission()` or the rejecting `fee_for_period()` helper.

## Non-Validating Aggregation

The raw builder computes the same deterministic interval values used by the
circuit:

- `dt`;
- odometer delta;
- fallback flag (`dt > cadence_sec`);
- charged distance and fee;
- total distance;
- total fee;
- fallback interval count;
- receiver fix root;
- interval commitment root.

It does not enforce receiver signatures, maximum authenticated-time delta,
odometer monotonicity, or circuit constraints. This allows a later subprocess
gate to prove that the circuit itself rejects invalid trajectories.

## Validation Rules

Both builders require exactly the profile fix count because the compiled k6
circuit has fixed-size arrays. Both derive `period_start_time`,
`period_end_time`, `month_id`, `month_start_time`, and `month_end_time` from
the supplied fixes. `payload_rem_zero=True` is the only supported mode in this
change; non-zero E3 residual handling is deferred.

## Tests

Add focused tests that:

1. prove an ablated `no_max_dt` request no longer returns honest fixes through
   the broad OSNMA/cadence fast path;
2. prove `build_input()` is field-for-field equivalent to
   `build_input_for_fixes(build_fixes(...), build_tariff(), ...)`;
3. prove the raw builder derives the 2026 month window and zero payload
   remainders;
4. prove the raw builder can serialize a deliberately invalid `dt >
   max_dt_sec` trajectory without Python rejection.


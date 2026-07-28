# WayBill P0 Closure Design

Date: 2026-07-28

Baseline: `cb2b251af5d1c94cad1f1ea6a26ad9da02828f7d`

Decision owner: project owner approved the recommended independent signer
process and authorized subsequent best-effort design choices.

## 1. Goal

Close the seven P0 findings in the 2026-07-28 engineering and paper review
before any formal server run:

1. instantiate the receiver trust boundary and authenticate interval validity;
2. replace the overbroad monthly-revenue theorem with a true scoped theorem;
3. make one V6 revision canonical across circuit, profile, runbook, artifact
   guide, and paper;
4. make S4 bucketed views mutually exclusive with exact views;
5. remove temporal overlap between S4 gallery and query windows;
6. implement the frozen S1 cluster bootstrap and a real month-close ablation;
7. replace the paper skeleton and self-declared formal receipts with reviewable,
   fail-closed evidence.

The implementation must not claim production readiness. The independent
receiver service is an artifact-grade process boundary with persistent state;
hardware acquisition, HSM integration, and operating-system hardening remain
deployment work.

## 2. Considered approaches

### A. Paper-only scope reduction

Keep the current signer helper and narrow every claim to an in-process
prototype. This is low cost but does not close the trusted-input finding and
does not justify a proof-only deployment path.

### B. In-process receiver object

Move key handling and root recomputation behind a Python class. This improves
encapsulation but leaves the prover and signer in one address space and cannot
support the intended trust-boundary argument.

### C. Independent persistent signer process — selected

Create a receiver service with a private key, authenticated acquisition API,
append-only SQLite log, anti-rollback checks, and a read-only attestation API.
The prover never supplies a root or statement to be signed. This is the
smallest design that closes the artifact-level trust-boundary gap without
pretending to be a hardware implementation.

## 3. Canonical protocol revision

The repaired circuit is `settlement-period-v6-validity-bound-k25-d8` with
commitment semantics `receiver-fix-validity-v2`.

For fix `i`, the fix commitment binds:

```
(device_attestation_commitment,
 policy_profile_commitment,
 period_id,
 fix_seq,
 authenticated_time,
 cell_x,
 cell_y,
 odometer_m,
 nonce,
 validity_to_next)
```

`validity_to_next` is `position_valid[i]` for non-terminal fixes and the
constant zero for the terminal fix. The circuit constrains every validity bit
to be Boolean before it enters the commitment. This preserves the existing 22
public signals while changing `receiver_fix_root`, the R1CS, proving key,
verification key, and policy-profile commitment. All prior V6 proof artifacts
are therefore versioned as legacy and cannot be accepted under the new profile.

The root-attestation signature covers only receiver-owned facts: version,
receiver identity, device identity, period identity, sealed-log epoch, fix
count, receiver fix root, and the enrolled receiver public-key commitment. It
does not cover the caller's statement commitment or bill. The Groth16 proof and
charger policy checks bind the signed root to the tariff-dependent statement.
This keeps pricing outside the receiver TCB.

## 4. Independent receiver signer

### 4.1 Process and storage

Add `services/receiver_signer/app.py` and a small storage module using the
Python standard-library `sqlite3` package. The process receives:

- an Ed25519 seed from a file path, never from a request;
- a SQLite database path;
- an acquisition bearer token used only by the trusted ingestion channel.

The database stores sealed period logs and per-device monotonic state. A
`(device_id, period_id)` log is immutable after insertion. Each log records the
canonical fixes, `position_valid` vector, policy-profile commitment, computed
root, creation epoch, and content SHA-256. Device state rejects decreasing fix
sequence, time, odometer, or log epoch across sealed periods.

SQLite transactions and unique constraints provide atomic append and replay
rejection. The artifact service supports one writer and concurrent readers;
multi-host consensus is out of scope.

### 4.2 APIs

`POST /v1/receiver/logs` is acquisition-only. It accepts raw fixes,
`position_valid`, and the policy-profile commitment, validates their shape and
monotonicity, recomputes the validity-bound root, and atomically seals the log.
It never accepts a caller-supplied root or public statement.

`GET /v1/receiver/logs/{device_id}/{period_id}/attestation` returns the sealed
root metadata and Ed25519 signature. It cannot create or alter a log.

`GET /health` returns process readiness without exposing logs or key material.

The proof script accepts a receiver URL and fetches an existing attestation. It
locally recomputes the root from its witness and refuses to prove if it differs
from the sealed receiver root. There is no private-seed fallback in the
paper-facing command. A separate fixture-loading command represents trusted
acquisition in tests and demos.

### 4.3 Negative guarantees

Tests must show that:

- a prover cannot ask the signer to sign an arbitrary root or statement;
- changing one validity bit changes the root and invalidates the attestation;
- duplicate, rollback, non-monotonic, and post-seal writes fail;
- an incorrect acquisition token fails;
- the charger rejects a valid proof paired with the wrong receiver log
  attestation.

## 5. S1 method repair

Each accepted period produces four explicit monetary outcomes:

- oracle position fee;
- submitted V5 time fallback fee;
- submitted V6 odometer fallback fee;
- whole-period withholding with and without monthly reconciliation.

With month close, a wholly withheld period contributes zero accepted-period
fee and its entire odometer distance is charged at canonical `r_max`. Without
month close, the withheld-period charge is zero. The latter is the actual
`v6-without-month-close` ablation; it is no longer copied from submitted V6.

Any malformed or rejected period makes the stage fail closed. The result keeps
the rejection ledger for diagnosis.

For every registered metric and percentile (50, 95, 99), S1 performs 5,000
deterministic bootstrap replicates by sampling original user/vehicle clusters
with replacement. A replicate includes all periods belonging to each sampled
cluster. The receipt records estimator, lower/upper 95% percentile interval,
cluster unit, replicate count, and seed.

## 6. S4 measurement repair

The observation schemas are mutually exclusive:

- O0: duration, interval count, exact fee, exact distance;
- O1: O0 plus exact fallback metadata;
- O2: duration, interval count, bucketed fee, bucketed distance, and fallback
  metadata, with no exact fee or distance;
- O3: O2 plus selectively opened cells.

The stage result records the sorted field list and its SHA-256. A validator and
unit test reject exact fields in O2/O3.

Sequence construction uses non-overlapping windows. For each identity, the
first eligible window is gallery; a pre-registered one-period temporal gap is
discarded; query windows start after the gap and never reuse gallery periods.
Subsequent queries are also non-overlapping. Training and testing identities
remain disjoint. The receipt records the temporal gap, discarded periods,
window period IDs, overlap checks, identity counts, and query counts. A job
fails if it cannot form a gallery and at least one non-overlapping query for
each retained test identity.

## 7. Formal receipt repair

`finish_stage` emits `waybill.formal.stage-result/v2` containing:

- exact job ID, stage, kind, and canonical job SHA-256;
- semantic status;
- a recursively generated artifact manifest with path, size, and SHA-256;
- a canonical result SHA-256.

`execute_job` marks an attempt passed only if the command exits zero and the
v2 stage result validates against the expected job and current files. The
attempt receipt contains its own canonical digest plus the validated stage
result and artifact-manifest digests.

`merge_run` revalidates every candidate attempt from disk. It rejects unknown
schemas, wrong job IDs or attempt numbers, command mismatch, missing stage
results, failed semantic status, path traversal, missing/tampered artifacts,
and digest mismatch. A hand-written `{"status":"passed"}` receipt must never
advance the aggregate.

Protocol validation is extended to freeze the S1 methods/statistics/rejection
policy and S4 schemas/split/gap. Gate receipts receive an allow-listed schema
and canonical payload hash; existing historical gate receipts are not silently
upgraded.

## 8. Canonical V6 deployment and artifacts

The default policy directory contains one active paper-facing V6 profile and
its tariff artifact. The profile names the repaired circuit, validity-bound
commitment semantics, odometer fallback semantics, and the regenerated
verification-key hash. The charger and runbook default to this profile.

The artifact guide becomes V6-first. It reports public-signal order,
constraints, proof/verify timings, backend, hardware, trial count, and hashes
only from the regenerated receipt. V5 remains explicitly labeled historical.

A machine-readable claim matrix binds each paper claim to assumptions, signer
contract, profile/circuit, test or theorem, receipt/hash, and figure/table.

## 9. Paper repair

The manuscript is rewritten around the independent signer and the canonical
V6 revision.

The monthly theorem is scoped to withholding completeness relative to the
authenticated-cell billing oracle:

- accepted distances retain the fee proven for their authenticated cells;
- unaccounted odometer distance is charged at `r_max`;
- whole-period withholding cannot reduce monetary payment relative to
  submitting that same authenticated-cell period;
- no claim is made that reconciliation corrects relay-induced zone
  misattribution.

Relay and quantization residuals are reported as an explicit economic error
term, not hidden in the theorem. Missing monthly attestation leads to a defined
administrative/default state, not a cryptographic revenue guarantee.

The privacy statement is a leakage declaration, not a simulation theorem,
unless a complete game and simulator are supplied. `first`, `zero roadside
enforcement`, `all driven distance`, and `deployable` are removed or qualified.

All TODO markers are resolved. Related work uses verified primary sources;
the bibliography is enabled. Placeholder performance numbers are replaced by
the regenerated V6 receipt, and figures/tables without valid evidence are
replaced by bounded text or auditable tables rather than invented results.

## 10. Verification gates

The change is complete only when all of the following pass:

1. receiver signer API/storage unit and integration tests;
2. Python/circuit differential tests for validity-bound commitments;
3. S1 bootstrap, ablation, and fail-closed rejection tests;
4. S4 mutually exclusive schema and zero-overlap tests;
5. fake/tampered receipt regression tests;
6. charger policy/profile and proof-only negative tests;
7. default `pytest` collects the full repository suite;
8. `script/run_pytests.sh` and `script/ci_local.sh` pass;
9. the repaired circuit compiles and a fresh witness/proof verifies;
10. `WayBill/main.tex` builds with zero TODO markers and an enabled
    bibliography;
11. claim matrix, README, runbook, profile, circuit, vkey, and receipt hashes
    agree;
12. the WayBill Obsidian Hub, Plan, experiment ledger, review status, and daily
    record are updated only after the executable gates pass.

## 11. Rollout and compatibility

This is a fail-closed protocol revision. Old V5 and pre-validity-bound V6
profiles, proofs, root attestations, and receipts are not accepted as the new
revision. Historical outputs remain available for provenance but cannot be
mixed into the repaired paper tables. The formal server run remains blocked
until a small adversarial dry run closes all twelve gates above.

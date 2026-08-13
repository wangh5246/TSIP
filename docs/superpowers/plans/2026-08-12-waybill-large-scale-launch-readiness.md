# WayBill Large-Scale Launch Readiness Implementation Plan

> **Execution rule:** use the `executing-plans` workflow task by task. The
> authority worktree is `/Users/wanghao/Projects/waybill_formal`.

**Goal:** freeze a corrected WayBill V6 release, materialize one canonical
four-dataset corpus on the target, and make every pre-`init-run` condition
machine-verifiable before M4 begins.

**Architecture:** `waybill-formal-readiness-v2` is immutable but superseded for
M4. The repaired worktree must pass local validation and then become a new
clean commit, annotated tag, OCI/SIF set, SBOM/scan set, and release bundle.
The actual Linux x86-64 target must independently pass RG6 and materialize the
data-dependent plan. No old static plan or uncommitted worktree may execute.

## Non-negotiable constraints

- Never initialize M4 from `waybill-formal-readiness-v2` at `f5f07e2...`.
- Never use `artifacts/waybill_formal/static-plan/plan.json`; it is
  `materialized=false` and has no final S3 cardinality.
- Preserve raw/provider-restricted and row-level data outside Git.
- Preserve every failed attempt and permit at most the frozen retry budget.
- Do not copy M4 values into the paper until strict merge passes.
- Do not commit, tag, publish, or upload without the user's authorization.

## Task 1 — Repair formal-run semantics

- [x] Replace S2/S5 symlinks with regular copied artifacts.
- [x] Build and anchor the S5 corpus as one valid 100-attestation chain.
- [x] Rename S5 server claim to in-process `handler`/SQLite functional scope.
- [x] Execute S3 as four-bucket groups; enforce main 1% and all-instance
      95%-within-5% gates at strict merge.
- [x] Treat any S3 checker/direction/small-oracle soundness failure as fatal.
- [x] Fail S1 identity bootstrap closed instead of using period identifiers.
- [x] Add descriptive S2 P99 fields and state the n=10 order-statistic limit.
- [x] Bind failed stage results into attempt receipts and retain explicit
      resource-rejection classification.
- [x] Emit hash-bound `failure-summary.json` and
      `scientific-aggregate.json` from selected immutable attempts.

## Task 2 — Restore and validate the canonical raw-data root

- [x] Restore Rome to
      `/Users/wanghao/Projects/waybill_data/raw/rome/Roma.txt`.
- [x] Verify size `1608435716` and SHA-256
      `ea282cd631b66ebbb79680939293956301be769282c9c02d0d989ecdf53e0cc1`.
- [x] Build the uncapped manifest in
      `artifacts/readiness/2026-08-12-data-manifest/`.
- [x] Pass RG2 with 29,029 raw files and all four datasets complete.

## Task 3 — Close local verification

- [x] Pass focused S1/S2/S3/S5 and strict-merge regression tests.
- [x] Pass the complete locked pytest suite (548 passed, 3 declared skips).
- [x] Pass `validate-config`, `git diff --check`, compilation and relevant
      lint/type gates.
- [x] Build the paper with bibliography/cross-references and visually inspect
      every rendered page.
- [x] Record exact commands, counts, hashes, and any skips in the dated review
      report.

## Task 4 — Freeze a new immutable release

- [x] Confirm the intentional diff; obtain user authorization to commit/tag.
- [x] Create one clean source commit and annotated successor tag.
- [x] Regenerate code manifest and protocol binding from that tag.
- [x] Rebuild all bound `linux/amd64` OCI roles.
- [x] Produce role-bound SPDX SBOMs and Trivy reports; satisfy policy.
- [x] Finalize and independently verify the successor release bundle.
- [ ] Transfer the bundle to the target and build an immutable SIF; record its
      SHA-256 separately from the OCI digest.

## Task 5 — Materialize and qualify the actual target

- [ ] Use Linux x86-64 with the frozen CPU/RAM/workspace thresholds.
- [ ] Transfer and validate the four authorized raw datasets and exact PTAU.
- [ ] Run uncapped preprocessing once into the read-only shared data root.
- [ ] Materialize all canonical S3 instances without silently dropped periods.
- [ ] Generate a materialized plan with non-null `expected_job_count`.
- [ ] Pass RG6 on the actual execution node using the exact successor SIF.
- [ ] Run one representative smoke for S1, S2-main, S3, S4, S2-concurrency,
      S5-corpus, S5-verifier, and S5-handler before the full arrays.

## Task 6 — Initialize and execute M4

- [ ] Confirm all RG0–RG8 receipts are present, bound, and `passed`.
- [ ] Run immutable `init-run` exactly once.
- [ ] Submit dependency-ordered arrays: S1, S2-main, S3, S4,
      S2-concurrency, S5-corpus, S5-verifier, S5-handler.
- [ ] Resume only failed jobs and only within the frozen retry budget.
- [ ] Run strict merge; require aggregate and S3 gate status `passed`.
- [ ] Generate paper tables/figures only from the hash-bound scientific
      aggregate, preserving all denominators and failures.

## Task 7 — Manuscript and knowledge-base closure

- [x] Narrow claims to receiver-sealed origin labels, formula-level S1,
      bounded-displacement S3, and in-process S5 handler scope.
- [x] Add closest-alternative, trust-boundary, dispute, fairness, availability,
      and governance limitations.
- [x] Expand the related-work base and keep canonical receipt distinct from M4.
- [ ] Fill author/ethics/funding/conflict/AI disclosure fields supplied only by
      the authors.
- [x] Update Hub, Plan, Index, registry, dated report, and lint receipt.

## Go rule

`GO = local_full_verification ∧ successor_release_verified ∧
target_RG6_passed ∧ plan.materialized ∧ all_stage_smokes_passed`.

If any term is false, the decision remains **Conditional No-Go** and
`init-run` is forbidden.

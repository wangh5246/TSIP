# TSIP Heatmap V4 Docker Smoke and Paper-Scale Experiment Design

Date: 2026-07-10
Status: Approved direction; written specification pending user review
Scope: `TSIP_heatmap_version` only

## 1. Objective

Build an isolated, reproducible Docker path for the TSIP heatmap method, prove
that the V4 relation is exercised end to end on all five datasets, and block
paper-scale N=1000 runs until protocol correctness and utility quality both pass
explicit smoke gates.

The five datasets are:

- T-Drive
- GeoLife
- Porto
- Rome
- Synthetic

The final paper-scale unit is one dataset, 1000 users, 10 evaluated rounds, and
one independent seed. The final evidence set uses at least three independent
seeds per dataset and includes clean and 10% malicious conditions.

## 2. Current-State Finding

The repository does not yet contain a paper-ready V4 Docker experiment.

1. Existing parallel N=1000 Docker runs load `zk/tsip_main`, not the recovered
   isolated V4 circuit.
2. The recovered V4 folder has R1CS and WASM artifacts but no proving key or
   verification key.
3. `run_experiment_rounds.sh` changes `CLIENT_USER_NAMESPACE` on every round.
   Every submission therefore appears to be a new enrollment and the run does
   not exercise accepted-predecessor follow-up proofs.
4. Existing smoke scripts are empty files.
5. Existing Docker CSV files report acceptance and reconstruction counters but
   do not contain utility metrics, independent seeds, confidence intervals, or
   baseline comparisons.
6. The recovered archived V4 relation accepts `share_content_commitment_a` and
   `share_content_commitment_r` as public values. It does not open those
   commitments in-circuit to the paper's stated `(primary, d_A, d_R, ctx)`
   values. This circuit/paper mismatch must be resolved before results can
   support the paper's C21 same-primary claim.

Existing N=1000 logs remain system-sanity evidence only. They must not be
included in a paper result table as V4 end-to-end measurements.

## 3. Chosen Approach

Use an isolated V4 runtime derived from the complete V3 method snapshot, then
apply only the V4 binding changes. Do not modify or relabel the root legacy
runtime.

Two explicit circuit profiles are retained during recovery:

- `v4-archive`: the recovered 14-public-input relation matching archived
  witness/public samples. It is used only for compatibility regression tests.
- `v4-paper`: the C21-complete relation used by Docker smoke and paper-scale
  experiments. It must bind the hidden primary, canonical A/R share-content
  digests, report context, and transport blob hash as stated by the paper.

If `v4-paper` changes public/private input counts or constraint counts, its
receipts must use those new measured values. Archived V4 performance numbers
must not be attached to the new circuit.

## 4. Isolation Layout

All new method-specific files live under:

```text
TSIP_heatmap_version/method_code_v4_isolated/
  circuits/
  runtime/client/
  runtime/common/
  runtime/shuffler/
  js/
  zk/v4_archive_k6/
  zk/v4_paper_k6/
  receipts/
```

Experiment orchestration and results live under:

```text
TSIP_heatmap_version/runtime/experiments-heatmap/
  docker_v4_smoke/
  docker_n1000_v4/
  analysis_v4/
```

A Compose override mounts the isolated client, common helpers, shuffler, and V4
artifacts. It uses a unique Compose project name and host port range per dataset.
Legacy containers and output directories are not reused.

## 5. Circuit and Artifact Gate

### 5.1 Archived compatibility profile

The existing archived input/public pairs for k6 and k30 must continue to pass:

- witness generation succeeds;
- public signals match exactly in order and value;
- Groth16 proof verification succeeds with newly generated test keys;
- R1CS reports 14 public inputs and 23 private inputs for the recovered profile.

### 5.2 Paper profile

The paper profile must implement and test all of the following:

- salted predecessor, current, and anchor location commitments;
- coordinate-to-primary quotient/remainder derivation;
- primary commitment opening;
- canonical channel-local digests `d_A` and `d_R`;
- A/R commitment openings tied to the same hidden primary and report context;
- payload commitment and transport blob hash binding;
- secret commitment, modeset membership, mode tag, step bounds, and ADWC caps;
- exact public-signal order documented in a machine-readable manifest.

The client computes commitments from the exact serialized share packages that
are sent. The shuffler recomputes transport binders. Each aggregator validates
its channel-local package and digest. A mismatch at any layer is a hard reject.

### 5.3 Setup receipts

Use a locally verified phase-2 Powers of Tau file large enough for the circuit.
Generate a development Groth16 setup for smoke and label it non-production.
Record:

- source commit and dirty-worktree marker;
- circuit source hash;
- R1CS, WASM, ZKey, and VKey SHA-256 hashes;
- snarkjs, circom, Node, Python, Docker, and image versions;
- R1CS constraint/input counts;
- setup command and elapsed time.

No smoke or scale run starts if the manifest and mounted container hashes differ.

## 6. Stateful Round Semantics

User identity must remain stable across rounds. Dataset and seed are part of the
namespace; round number is not.

For k6, each condition runs:

- one enrollment round;
- five additional warmup rounds using the same users and circuit path;
- at least two evaluated follow-up rounds with real proofs.

Warmup submissions may be held from aggregation, but they must still execute the
same proof path. The runner records separate counters for enrollment, warmup
proofs, evaluated proofs, proof verification success, policy rejects, malformed
payload rejects, and aggregation inclusion.

A run cannot pass merely because the client process exits with code zero.

## 7. Smoke Gates

Smoke has three layers. All are required.

### 7.1 Static and cryptographic smoke

Run unit/fixture checks for:

- archived V4 sample compatibility;
- paper-profile positive proof;
- tampered public signal;
- tampered current coordinate;
- swapped primary;
- swapped A share, swapped R share, and A/R cross-swap;
- changed context and changed blob hash;
- wrong predecessor and wrong anchor;
- replayed proof in a new round.

Gate: every positive fixture verifies and every negative fixture is rejected at
the intended layer.

### 7.2 Five-dataset Docker protocol smoke

Run five isolated Compose projects in parallel with:

- `CLIENT_TOTAL=10`;
- k6 profile;
- 6 warmup/enrollment rounds plus 2 evaluated rounds;
- one clean condition and deterministic attack conditions;
- fixed, recorded seeds;
- full Groth16 proving and verification enabled.

Clean gate for every dataset:

- honest false-reject rate is 0;
- evaluated proof attempts equal expected users times evaluated rounds;
- proof verification success rate is 1;
- A and R accepted counts are equal;
- secure reconstruction succeeds;
- DP release reports no error;
- no enrollment-only shortcut appears in evaluated rounds.

Attack gate for every dataset:

- binding-swap attacks have malicious rejection rate 1;
- replay and predecessor/anchor tampering have malicious rejection rate 1;
- honest false-reject rate remains 0;
- rejection reason counters identify the expected failed invariant.

### 7.3 Utility-quality smoke

Run the utility evaluator inside Docker on all five complete 1000-user inputs.
Use 10 rounds and at least three independent seeds. Compare the proposed method
against tuned comparable baselines under the same epsilon, malicious rate,
rounds, input split, and seed set.

Primary metric: top-50 Jaccard, higher is better.

Secondary metrics: RMSE and relative error, lower is better; malicious rejection
rate and honest false-reject rate are integrity guardrails.

The initial quality gate is:

- the proposed method's mean Jaccard is at least the strongest comparable
  baseline's mean on at least four of five datasets;
- no dataset trails the strongest comparable baseline by more than 0.02 absolute
  Jaccard;
- honest false-reject rate is at most 1%;
- deterministic binding attacks have at least 99% rejection;
- no result is selected from a failed or incomplete run.

For smoke, these are optimization admission thresholds, not paper significance
claims. Failure triggers one-variable-at-a-time diagnosis and tuning. It does not
permit launching the cryptographic N=1000 scale run.

## 8. Optimization Protocol

Tune only after correctness gates pass. Preserve a fixed comparison protocol and
change one factor per attempt.

Tunable factors, in order:

1. release epsilon under the paper's privacy budget;
2. DP threshold parameters `tau` and `tau2`;
3. payload sparsity and dummy allocation, if permitted by the method definition;
4. ADWC policy-cap ratio, subject to the integrity constraint;
5. k6 versus k30 as a separate profile comparison, not a pooled result.

Each attempt records purpose, complete setting, seed list, per-round results,
analysis, and next action. Per-dataset epsilon cherry-picking is reported only as
an explicitly labeled optimized upper-bound result. The main comparison uses a
predeclared fair setting.

## 9. Paper-Scale Experiment

The cryptographic scale run starts only after all smoke status files say `pass`.

For each dataset and seed:

- 1000 stable users;
- 6 k6 warmup/enrollment rounds;
- 10 evaluated rounds;
- full V4 proving and verification;
- clean and 10% malicious conditions;
- identical comparison settings and immutable container image digests.

Five datasets run as isolated Compose projects with separate ports, state paths,
logs, CSV files, dumps, and status receipts. Seeds run as separate immutable
experiment units. Failed units are rerun under a new attempt identifier and are
never silently overwritten.

The launch tool supports `--dry-run`, `--resume`, dataset/seed selection, and a
global resource cap. It prints the exact commands and estimated proof count
before starting.

## 10. Statistical and Paper Gate

The final analysis states the unit of analysis as an independent seeded run, not
an individual client report. For every method/dataset/condition it reports:

- seed count;
- mean, standard deviation, and 95% confidence interval;
- paired comparison against the strongest fair baseline;
- effect size and multiple-comparison correction;
- all failed/missing runs and exclusion reasons.

Paper admission requires:

- at least three complete independent seeds per cell;
- protocol and artifact receipts matching the analyzed rows;
- no silent missing values;
- utility quality gate retained at scale;
- every headline method claim backed by a controlled baseline or ablation;
- circuit counts and performance numbers taken from the exact paper-profile
  artifacts used in Docker.

If these conditions fail, the result is labeled diagnostic and is not copied into
paper tables.

## 11. Failure Handling

Every command writes an atomic status file with `running`, `pass`, or `fail` and a
machine-readable failure reason. Status `complete` is not accepted as a quality
decision.

The runner fails immediately on:

- container artifact hash mismatch;
- wrong public-signal count/order;
- zero evaluated proof attempts;
- all-enrollment evaluated rounds;
- reconstruction or DP errors;
- missing utility dumps;
- NaN/empty metrics;
- gate threshold violation.

Containers remain available after a failed smoke for log inspection. Cleanup is
an explicit separate command.

## 12. Required Outputs

Smoke output:

```text
docker_v4_smoke/
  manifest.json
  gate_status.json
  protocol/<dataset>/<condition>/
  utility/<dataset>/<seed>/
  logs/
  experiment-log.md
```

Paper-scale output:

```text
docker_n1000_v4/
  manifest.json
  run_matrix.csv
  <dataset>/<seed>/<condition>/
  combined_metrics.csv
  status.json
```

Strict analysis output:

```text
analysis_v4/
  analysis-report.md
  stats-appendix.md
  figure-catalog.md
  figures/
```

## 13. Non-Goals

- Reusing legacy N=1000 receipts as V4 results.
- Claiming statistical superiority from the N=10 protocol smoke.
- Optimizing by choosing only successful seeds or datasets.
- Changing unrelated root services or RUC experiments.
- Treating a development Groth16 setup as a production ceremony.


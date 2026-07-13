# TSIP Heatmap TDSC Revision Design

Date: 2026-07-13

## Decision

The target venue is IEEE Transactions on Dependable and Secure Computing
(TDSC). The approved revision strategy is a staged, evidence-first revision:
complete all paper work that does not depend on the final two N=1000 units,
then insert the final scale statistics only after the 15/15 receipt exists.

## Objective

Produce a reviewer-facing SHTPC manuscript whose method description,
experimental claims, artifact facts, submission compliance, and reproducibility
package agree with the current V4 implementation. Every major claim must point
to a directly auditable receipt, table, figure, theorem, or explicit deployment
assumption.

## Source Of Truth

Evidence is resolved in this order:

1. V4 manifest hashes and the R1CS/proving artifacts used by Docker.
2. Static, protocol, utility, and per-unit JSON receipts.
3. Generated aggregate CSV/JSON and publication figures.
4. The active manuscript at `TSIP/main.tex`.
5. Historical reports and conversation summaries.

Historical receipts remain citable as historical measurements, but they must
not define the current circuit if their public-input order, constraint count,
or proving key differs from the manifest-bound paper artifact.

## Current Baseline

- The active title is SHTPC.
- The abstract is approximately 247 words and exceeds the IEEE Computer Society
  regular-paper abstract range of 100 to 200 words.
- The current PDF is a 17-page artifact generated on 2026-07-07 and is not a
  fresh verification of later experiment work.
- The manuscript still describes two public datasets plus derived subsets and
  uses an N=50 headline setup.
- The fixed five-dataset N=1000 utility comparison is complete.
- The V4 cryptographic scale matrix is 13/15 complete; Rome/303 and
  Synthetic/303 are interrupted at 3/16 rounds.
- The manifest-bound paper R1CS currently reports 3,547 constraints, 16 public
  inputs, and 25 private inputs. The manuscript still contains 3,056, 14, and
  23 in several places.
- `TSIP/main.tex` is staged as deleted while a replacement at the same path is
  untracked. This must be resolved without discarding either version.
- The repository lacks `LICENSE` and `DATA_NOTICE.md`.

## Scope

### Stage 0: Preservation And Git Hygiene

- Record hashes and timestamps for the active manuscript, bibliography,
  generated PDF, V4 manifest, and key result receipts.
- Compare the staged historical `TSIP/main.tex` with the untracked working
  replacement before changing the index.
- Preserve the active manuscript and leave unrelated staged changes untouched.
- Restore a single intentional tracked state for the active manuscript only
  after the content relationship is understood.

### Stage 1: Artifact And Method Consistency

- Trace the exact circuit, R1CS, WASM, zkey, vkey, bindings, client, and
  shuffler files selected by `docker_v4_smoke/manifest.json`.
- Generate one canonical artifact-facts record from tools rather than prose.
- Reconcile constraint count, public/private inputs, public-signal ordering,
  proof size, report-frame size, and setup identifiers across the Method,
  Security, Evaluation, Conclusion, and included tables.
- Distinguish the 14-input archive compatibility relation from the 16-input
  paper circuit. Do not merge their measurements.
- Retain the scoped claim: SHTPC proves admission consistency, not physical
  presence, source authenticity, or general poisoning robustness.

### Stage 2: Paper Story And Core Writing

- Keep the central insight that trajectory continuity and payload validity must
  be bound in one zero-knowledge admission relation.
- Compress the abstract to 100 to 200 words with problem, gap, method, evidence,
  and limitation represented once each.
- Reverse-outline Introduction, Method, Evaluation, Discussion, and Conclusion.
- Give every paragraph one explicit message and a topic sentence that supports
  the section thesis.
- Remove or weaken claims whose evidence is historical, incomplete, or outside
  the modeled boundary.
- Keep SHTPC terminology stable and rename stale internal TSIP labels where this
  does not break references.

### Stage 3: Five-Dataset Evidence Integration

- Describe T-Drive, GeoLife, Porto, and Rome as real datasets and Synthetic as a
  synthetic stress dataset.
- Separate three evidence layers:
  - original-input fixed utility evaluation;
  - safe-trajectory Docker protocol execution;
  - full Groth16 N=1000 scale execution.
- Add the fixed fair utility comparison at epsilon 5.0 and tau 2.0, including
  means, standard deviations, honest FRR, MRR, and absolute delta against the
  strongest baseline.
- State that per-dataset tuned settings are an upper-bound view and are not the
  main fair comparison.
- Do not state that the full three-seed cryptographic matrix is complete until
  `launch_status.json` records 15/15 pass and all unit receipts pass validation.

### Stage 4: Compliance And Reproducibility

- Add a repository license appropriate to the code and manuscript assets after
  checking ownership boundaries.
- Add `DATA_NOTICE.md` with source, citation, download, license, redistribution,
  preprocessing, and synthetic-generation rules for all five datasets.
- Audit new and high-risk references for existence, metadata, and claim-level
  support.
- Prepare explicit data availability, code availability, ethics, AI-use,
  conflict-of-interest, and prior-version statements for author confirmation.
- Document that simulated review reports are internal quality-control artifacts
  and not external peer review.
- Create a reproducibility index linking commands, environments, manifests,
  hashes, receipts, tables, and figures without redistributing restricted raw
  trajectories.

### Stage 5: Build And Visual Verification

- Compile with Biber and enough LaTeX passes to resolve all references.
- Fail the gate on undefined citations/references, missing figures, fatal
  warnings, or stale rerun requests.
- Record nonfatal underfull/overfull warnings and fix those that harm reading.
- Recount pages from the newly generated PDF.
- Render and inspect every page for float placement, clipped tables, unreadable
  labels, duplicated captions, blank regions, and inconsistent typography.
- Verify that all plotted values trace to generated artifacts.

### Stage 6: Final Scale Handoff

This stage begins only after Rome/303 and Synthetic/303 pass.

- Validate 15 units, 16 rounds per unit, zero proof failures, 10 evaluation
  rounds, A/R 1000/1000, and successful reconstruction and DP release.
- Generate aggregate statistics across all three seeds, including variability
  and throughput rather than only best-case values.
- Update the scalability subsection, final result table, abstract evidence, and
  conclusion exactly once from the generated aggregate artifact.
- Change the Obsidian result status from `partial-verified` to `verified` only
  after these gates pass.

## Claim-Evidence Contract

Each Abstract and Introduction claim will be entered into a map with:

`Claim | Evidence artifact | Manuscript location | Status | Required action`

Allowed statuses are `supported`, `partial`, `analytical`, `assumption`, and
`unsupported`. Unsupported claims are removed. Partial claims are narrowed or
held until the missing receipt exists.

## Obsidian Write-Back Protocol

Progress is not considered complete until the project knowledge base is
updated.

- `Daily/2026-07-13.md`: append each execution checkpoint and verification.
- `00-Hub.md`: maintain current focus, blockers, and latest verified state.
- `01-Plan.md`: update checkboxes immediately after each gate passes.
- `Writing/论文修订与投稿决策.md`: record manuscript decisions, page count,
  abstract length, and claim changes.
- `Knowledge/V4方法与证据边界.md`: record canonical artifact facts and claim
  boundaries.
- `Experiments/V4-Docker-N1000完整实验.md`: record only execution changes.
- `Results/Reports/V4实验结果-2026-07.md`: record only receipt-backed results.
- `_system/registry.md` and `_system/lint-report.md`: refresh and verify after
  each substantial synchronization.

No conversation-only completion claim is allowed.

## Error Handling And Preservation

- Never overwrite experiment receipts or source datasets.
- Never rerun passed scale units unless explicitly requested.
- If artifact facts disagree, stop manuscript propagation and resolve the
  selected artifact first.
- If a manuscript edit breaks a reference or build, restore only the edit from
  the current work unit, not unrelated user changes.
- If current evidence is incomplete, preserve the limitation in the prose and
  Obsidian status rather than substituting an estimate.

## Verification Gates

The independent-paper stage is complete when:

- the active manuscript is preserved in an intentional Git state;
- abstract length is 100 to 200 words;
- all current circuit facts match the manifest-bound artifact;
- five-dataset fixed utility is represented without mixing smoke trajectories;
- every major claim has a claim-evidence status;
- required compliance and reproducibility files exist or are explicitly blocked
  on author input;
- a fresh PDF compiles with no undefined references or citations;
- visual inspection is complete;
- Obsidian lint reports zero broken links, missing registry entries, and missing
  index entries.

The full revision is complete only after the 15/15 scale gate and its final
paper/Obsidian propagation also pass.

## Out Of Scope

- Production deployment, ceremony execution, key custody, or security
  hardening.
- New method invention unrelated to the V4 audit.
- Tuning against test labels or replacing the fixed fair comparison with
  per-dataset cherry-picked settings.
- Rewriting unrelated RUC, SA-HTD, patent, or admissions materials.

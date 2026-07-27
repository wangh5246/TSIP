# TSIP Submission Implementation Plan

Date: 2026-07-27

Source design: docs/superpowers/specs/2026-07-27-tsip-notation-baseline-submission-design.md

## Execution Rules

- Work only on branch codex/tsip-heatmap-tdsc-revision.
- Preserve the existing dirty worktree. Stage and commit only exact files created or changed by this execution.
- Treat heatmap-version/TSIP/main.tex as the canonical manuscript.
- Treat heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap as the canonical experiment root.
- Keep the repaired actor-aware matched utility matrix frozen unless an input, attack, decision rule, aggregation path, or metric changes.
- Exclude the superseded safe-trajectory queue from real-data claims.
- Admit no simulated cryptographic timing.
- Write every experiment attempt to a trajectory log before advancing its gate.
- Stop for user direction only under the stop conditions approved in the design specification.

## Frozen Inputs

The matched utility source is final_experiments/p8_matched_utility. Its status records 14,400 rows and state pass. The bound input manifest hash is b7fe95d39cb2cc63ee30792ad08610bff183474e3f1c323fd2ef3aeccc5f3092. T-Drive, GeoLife, Porto, and Rome contain 1,000, 16, 441, and 313 actors. These outputs replace the superseded safe-trajectory queue for real-data evidence.

The current SHTPC-Full circuit is method_code_v4_isolated/zk/v4_paper_k6. It contains 9,393 constraints and 19 public inputs. The native Prio3Histogram component is pinned to libprio commit 1ea3f6a35070c023fdfdef93ab3f39ca8d2215fa.

## P12. Extension Registry and Evidence Isolation

Files:

- heatmap-version/TSIP/P0_P11_EXECUTION.md
- heatmap-version/TSIP/CLAIM_EVIDENCE_MAP.md
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/pipeline-tracker.md
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/stage1_baselines/trajectory.md

Actions:

1. Append P12 through P22 gates to the execution record.
2. Register the repaired matched utility status and mark the old safe-trajectory queue as protocol-only evidence.
3. Create the extension pipeline tracker and Stage 1 trajectory log.
4. Record exact source, artifact, input, and configuration paths before implementation begins.

Gate:

- No final claim or figure source resolves to the superseded safe-trajectory directory.

Verification:

- Search the manuscript, claim map, figure generator, and final manifest for the old directory name.
- Validate the repaired input preflight report and p8 matched utility status.

## P13. Common Baseline Contract

Files:

- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baselines/submission_contract.py
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/tests/test_submission_baselines.py

Actions:

1. Add immutable report fixtures containing trajectory primary, measurement cell, context, and expected A6 outcome.
2. Add shared timing, percentile, hashing, receipt, and native-Prio3 helpers.
3. Define a common result schema for scheme, same-primary behavior, trust model, constraints, prove time, verify time, bytes, throughput, honest acceptance, and A6 rejection.
4. Write failing tests for honest acceptance, A6 behavior, receipt completeness, and rejection of empty or out-of-domain fixtures.

Gate:

- All adapters consume the same fixture and emit the same schema.

Verification:

- Run python -m unittest tests.test_submission_baselines before and after implementation.

## P14. Report-Local ZK + Prio3

Files:

- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baseline_circuits/report_local_filter.circom
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baselines/report_local_zk_prio3.py
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/stage1_baselines/trajectory.md

Actions:

1. Implement a report-local Groth16 relation that validates coordinate decomposition, domain membership, binary contribution, and a report-local primary commitment.
2. Keep the Prio3 measurement cell independent from the proof-derived primary.
3. Compile the circuit, generate a proving key, export the verification key, and record all artifact digests.
4. Execute an honest report and a valid mismatched-primary A6 report through the proof and pinned native Prio3 paths.

Gate:

- Honest reports pass both components.
- A valid mismatched-primary report also passes, matching the registered report-local interface.
- At least one real Groth16 proof is generated and verified.

Budget:

- Six implementation or diagnostic attempts.

## P15. Proof-Bound Prio3

Files:

- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baseline_circuits/proof_bound_admission.circom
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baseline_circuits/proof_bound_encoding.circom
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baselines/proof_bound_prio3.py
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/stage2_proof_bound/trajectory.md

Actions:

1. Implement an admission proof that derives a primary and binds it to a shared commitment.
2. Implement a separate encoding proof that binds the Prio3 measurement cell to the same commitment.
3. Verify both proofs before native Prio3 processing.
4. Record combined proof, verification, communication, and A6 behavior.

Gate:

- Honest reports pass both proofs and Prio3.
- A mismatched-primary report fails the encoding proof or shared-commitment equality check.
- The result is described as a Whisper-inspired adaptation rather than a Whisper reproduction.

Budget:

- Eight implementation or diagnostic attempts.

## P16. Trusted Bridge + Prio3

Files:

- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baselines/trusted_bridge_prio3.py
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/tests/test_submission_baselines.py

Actions:

1. Add a plaintext same-primary checker before native Prio3 processing.
2. Measure checker and Prio3 costs separately and jointly.
3. Label the row as a different-trust-model upper bound.

Gate:

- Honest reports pass.
- Every registered A6 mismatch is rejected before Prio3 aggregation.
- The receipt identifies the plaintext trust assumption.

## P17. Direct Unified-Vector Ablation

Files:

- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baseline_circuits/direct_unified_vector_base.circom
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baseline_circuits/direct_unified_vector_k6.circom
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/baselines/direct_unified_vector.py
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/stage3_direct_vector/trajectory.md

Actions:

1. Preserve the SHTPC K = 6 trajectory and primary relation.
2. Replace the fingerprint payload bridge with a 10,000-entry public vector.
3. Constrain every entry to be binary, constrain the total to the contribution bit, and constrain the weighted index to the trajectory-derived primary.
4. Compile, set up, prove, verify, and record the exact public-input and communication expansion.
5. Label the construction as a public-vector diagnostic ablation. Do not claim equivalent index privacy.

Gate:

- Honest one-hot vectors verify.
- Non-binary, two-hot, zero-hot, and wrong-primary vectors fail.
- Constraint count and verifier cost are obtained from the actual circuit.

Budget:

- Ten implementation or diagnostic attempts shared with P16.

Stop condition:

- Request user direction if the direct-vector circuit does not compile within the approved budget.

## P18. Unified Same-Hardware Benchmark

Files:

- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/run_submission_baseline_suite.py
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/stage4_benchmark/trajectory.md
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/baseline_results.csv
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/final_experiments/submission_extension/baseline_receipt.json

Actions:

1. Run Oracle-Clean, Natural-Composition, Report-Local ZK + Prio3, Proof-Bound Prio3, Direct Unified-Vector, Trusted Bridge + Prio3, and SHTPC-Full on one registered fixture.
2. Use one warm-up and at least 30 measured repetitions for cryptographic timing.
3. Measure proving mean, p50, p95, verification mean and p95, bytes, constraints, and A6 rejection.
4. Measure verifier throughput at 1, 2, and 4 workers for the applicable proof paths.
5. Write atomic CSV and JSON receipts containing source, binary, circuit, configuration, fixture, and output hashes.

Gate:

- Every timed row passes the fairness contract.
- No timing is simulated or copied from a paper.
- All rows use the Apple M4 host and the same fixture.

Budget:

- Six benchmark or diagnostic attempts.

## P19. Merged Figures and Tables

Files:

- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/generate_final_figures.py
- heatmap-version/TSIP_heatmap_version/runtime/experiments-heatmap/generate_submission_baseline_table.py
- heatmap-version/TSIP/figures/fig_final_robustness_combined.pdf
- heatmap-version/TSIP/tables/tab_submission_baselines.tex

Actions:

1. Merge the four-dataset robustness evidence into one double-column two-panel figure.
2. Use method color, dataset marker, direct endpoint labels, and a shared legend in Panel a.
3. Use a dataset by attack-strategy contamination-gap heatmap in Panel b.
4. Generate the unified baseline table from the benchmark CSV.
5. Export vector PDF and a 600 dpi raster QA copy.

Gate:

- Source-data validation passes.
- Labels remain readable at final printed size.
- No plotted value is manually edited.

## P20. Main Notation and Method Compression

Files:

- heatmap-version/TSIP/main.tex

Actions:

1. Add MAIN NOTATIONS AND THEIR DESCRIPTIONS after the opening Report and Admission Model text.
2. Normalize the coordinate object, primary cell, aggregation vector, accepted set, heatmap, and leakage notation.
3. Keep fingerprint symbols local to the bridge construction.
4. Delete Circuit Constraint Details in full.
5. Replace the C1 through C20 narrative inventory with the semantic jobs of the unified relation.
6. Retain C21 only as the fingerprint payload bridge.
7. Split long paragraphs and sentences while preserving theorem scope and proof assumptions.

Gate:

- Core symbols have one canonical meaning.
- The deleted subsection has no active reference.
- Definitions and theorems retain all conditions needed by Games 2 and 3.

## P21. Evaluation and Conclusion Rewrite

Files:

- heatmap-version/TSIP/main.tex
- heatmap-version/TSIP/CLAIM_EVIDENCE_MAP.md
- heatmap-version/TSIP/CITATION_AUDIT.md

Actions:

1. Replace Experimental Setup with the four required labeled paragraphs.
2. Insert the merged robustness figure and unified baseline table.
3. Remove repeated plot values, raw hashes, hash procedure details, and theory exposition.
4. State adapted baseline provenance and trust differences precisely.
5. Retain only trend-level robustness interpretation and GeoLife uncertainty.
6. Integrate discussion and limitations into a concise Conclusion followed by Future Work.
7. Update claim and citation audits for Prio3, EIFFeL, Whisper, Mastic, and Secure Stateful Aggregation.

Gate:

- Evaluation occupies no more than 4.5 pages.
- Every baseline has a clear source or adaptation label.
- No experimental paragraph introduces a theorem or new theoretical claim.

## P22. Submission Audit

Files:

- heatmap-version/TSIP/main.pdf
- heatmap-version/TSIP/TDSC_SELF_REVIEW.md
- heatmap-version/TSIP/P0_P11_EXECUTION.md

Actions:

1. Run all focused Python, circuit, proof, native Prio3, and figure-source tests.
2. Compile LaTeX and Biber to convergence.
3. Audit undefined citations, references, overfull boxes, font embedding, and final-size figures.
4. Audit active prose for we, can, must, colon, semicolon, em dash, long paragraphs, long sentences, and terminology drift.
5. Confirm the Conclusion ends in the first column of page 16 and References begin in the second column.
6. Perform a final claim-to-evidence and source-attribution audit.
7. Mark P12 through P22 complete only after all gates pass.

Gate:

- The manuscript is submission-ready under the approved design and all measured claims have passing receipts.

Stop condition:

- Request user direction if the 15.5-page target remains unmet after removing repeated numeric narration, artifact-level detail, redundant related work, and secondary scaling prose in that order.

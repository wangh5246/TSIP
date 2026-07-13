# TDSC Pre-Scale Adversarial Self-Review

Review date: 2026-07-14. Canonical manuscript: `TSIP/main.tex`. This review is
an internal quality-control record, not independent peer review. Its scientific
status is **pre-scale verified**: the fixed five-dataset utility and all
non-scale manuscript evidence pass, while current-circuit latency and throughput
remain withheld pending the strict 15-unit aggregate.

## Submission Verdict

- Scientific writing and non-scale evidence: **pass**.
- Five-dataset fixed utility at N=1000: **pass**, with the small Porto and
  Synthetic gains disclosed rather than generalized.
- Current N=1000 Docker performance claim: **not yet paper-ready**. The launcher
  reports 15/15 execution pass, but CE23 remains `partial` until every unit
  receipt is validated and hash-bound by the strict aggregate.
- Public release and submission declarations: **blocked on author action**.

## Blocking Author Gate

**BLOCKED: explicit author license selection required**

The repository has no approved top-level license. A `LICENSE` file must remain
absent until the authors select an SPDX license and confirm that all copyright
holders authorize it. Dataset and dependency licenses do not answer this gate.
The additional unresolved author confirmations are final author identity and
order, affiliations and ORCIDs, corresponding-author details, COI, prior or
concurrent versions, funding text, institutional ethics determination, code and
data availability wording, and the venue-required AI-use disclosure. The
author-owned checklist is `docs/submission/TSIP_HEATMAP_AUTHOR_CONFIRMATIONS.md`.

## Verified Build Receipt

The clean build sequence was:

```bash
cd TSIP
pdflatex -interaction=nonstopmode -halt-on-error main.tex
biber main
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

Build and inspection results before this review's final-scale work:

- Abstract: 155 words; manuscript checker issues: 0.
- Biber: 90 citekeys; warnings/errors: 0.
- PDF: 18 pages, US letter, PDF 1.7.
- Undefined citations/references, fatal errors, rerun requests: 0.
- Overfull boxes, LaTeX warnings, package warnings: 0.
- Underfull boxes: 42; all 18 pages were rendered, the Task 8 full-page review
  remained valid, and the modified Threat Model flow on pages 5--7 was
  re-inspected with no clipping, overlap, or unreadable text.
- SHA-256: `main.tex` `77e57e4cefa99814bed486fd9fcaa6bfb21adbd927de155effe001b6da792e12`;
  `reference.bib` `c1c4d078c2e2acf21a204312d2f62bb2a0e71b96e17b50926d35d11ededfb6cf`;
  `main.pdf` `b28bc819eac06711bebf42b551b7ae4c65d13bbc38d8a26c88a5fdf65e7bdfcb`.
- Task 8 verified checkpoint commit: `d54ac1a5`; the self-review edits and new
  build receipt belong to the Task 9 commit.

These are pre-scale self-review hashes, not final submission hashes. The full
clean build, warning scan, manuscript checker, mirror comparison, and 18-page
visual gate must run again after strict-scale integration.

## Claim-Evidence Closure

`TSIP/CLAIM_EVIDENCE_MAP.md` contains 27 major claims: 17 `supported`, seven
`analytical`, two `assumption`, one `partial`, and zero `unsupported`. CE01 is
closed by the source-level citation audit. CE26 is closed by the Heatmap
artifact index and executable rerun contract. The earlier MDS/EETS analogy was
removed: CE25 now states administrative separation as an explicit assumption,
not as evidence that operators will not collude. CE23 is the only remaining
partial claim and is excluded from the Abstract.

## Five-Dimension Review

Statuses are `pass`, `needs revision`, or `needs new experiment`. A pass means
the manuscript's scoped claim is supported; it does not turn an excluded threat
or assumption into a guarantee.

| Dimension | Skeptical reviewer question | Status | Evidence and disposition |
|---|---|---|---|
| Contribution | What new knowledge is delivered? | pass | The paper isolates the hidden trajectory/payload same-primary composition gap and defines one stateful admission relation that closes it. |
| Contribution | Is the failure case meaningful rather than syntactic? | pass | A valid trajectory proof can otherwise be paired with routed payload material for another primary; the separation lemmas and A6 ablation identify the missing equality. |
| Contribution | Is novelty scoped honestly? | pass | The paper claims a new admission property and system composition, not a new SNARK, DP mechanism, physical-location proof, or general poisoning defense. |
| Contribution | Are empirical gains exaggerated? | pass | All five fixed-protocol deltas are reported; +0.007 on Porto and Synthetic is explicitly called small. |
| Writing clarity | Can the relation and protocol be reproduced? | pass | Method fields, C1-C21, integer semantics, state transition, timing, warmup, artifact paths, commands, and pass criteria are explicit. |
| Writing clarity | Are terminology and evidence layers stable? | pass | SHTPC is the visible term; archive, historical-performance, current static/smoke, fixed utility, and current scale are kept non-interchangeable. |
| Writing clarity | Does paragraph flow support the paper story? | pass | The 89-entry reverse outline maps each core prose paragraph to one topic sentence, role, and claim set. |
| Experimental strength | Are results consistent across inputs and seeds? | pass | The fixed configuration has a positive SHTPC-minus-Nebula Jaccard delta for every dataset mean and for each of the 15 dataset-seed pairs; means and standard deviations are reported. |
| Experimental strength | Is absolute utility hidden when it is low? | pass | Absolute Jaccard spans 0.135 to 0.878; the manuscript reports each value and does not claim uniformly high utility. |
| Experimental strength | Are failure cases visible? | pass | Metadata inference, in-envelope pollution, false genesis, transfer, collusion, and development-setup limits appear in the Abstract, RQ3/RQ4, Discussion, or Artifact section. |
| Experimental strength | Is current-circuit cost established? | needs revision | Fifteen execution units pass, but no latency/throughput statistic may enter the paper until strict receipt validation and aggregation complete. |
| Evaluation completeness | Are key mechanisms ablated? | pass | No-ADWC, No-Payload-Bind, Stateful-ContextCommit, and No-Admission-Check expose the predicates responsible for A3 and A6. |
| Evaluation completeness | Is the main comparison fair? | pass | One epsilon/tau pair, N=1000, ten windows, 10% A1, and seeds 101/202/303 are fixed across all five datasets; tuned settings are excluded from the headline. |
| Evaluation completeness | Are datasets and evidence layers broad enough? | pass | Four real trajectory-derived inputs and one generated stress input are used; utility, smoke, and scale answer separate questions. |
| Evaluation completeness | Are baseline claims bounded? | pass | Nebula is called the strongest among evaluated fixed-configuration baselines, while VDAF/TEE/proof-of-location systems remain analytical design points rather than falsely comparable implementations. |
| Method soundness | Are assumptions explicit and falsifiable? | pass | SRV-TS, SCS, CA3, setup, hash, channel, and non-collusion assumptions are stated with adjacent failure consequences. |
| Method soundness | Does one relation actually bind routed payload to trajectory state? | pass | C17-C21, route/binder negative fixtures, Aggregator validation, and the manifest-bound 22-check gate cover the stated interface. |
| Method soundness | Does the design overclaim source authenticity or robustness? | pass | The claim begins post-enrollment and excludes physical presence, metadata elimination, fully in-envelope false reports, and malicious-Shuffler state forks. |
| Method soundness | Is net benefit supported at paper scale? | needs revision | Close CE23 with current-relation latency distribution, throughput, proof/verification totals, failure rate, reconstruction, and DP receipts before making a practicality claim. |

No additional utility rerun is required by this review. The remaining scientific
work is strict validation and aggregation of the already completed 15-unit
current-circuit matrix; any invalid unit discovered by that validator must be
rerun before the result can be marked verified.

## Exact Deferred Scale Work

1. Validate all five datasets times three seeds against the expected matrix,
   current manifest hash, launch-plan/status hash, N=1000, six warmup rounds,
   ten evaluation rounds, and `state=pass`.
2. Require 16 completed rounds per unit, zero unit/round failures, complete
   proof-generation and proof-verification accounting, A/R totals of 1000/1000
   in every evaluation round, successful reconstruction, and successful DP
   release.
3. Hash-bind every validated unit receipt and emit deterministic aggregate
   JSON, CSV, and LaTeX artifacts with all-unit and per-dataset mean, standard
   deviation, min/max, and throughput statistics. Do not report only the best
   seed.
4. Bind the strict aggregate into `paper_evidence.json`, update CE23 and RQ6
   only from generated macros/tables, and keep protocol-scale results separate
   from original-input RQ5 utility.
5. Re-run focused tests, manuscript contract checks, clean LaTeX/Biber build,
   warning scans, canonical/mirror byte comparison, and 18-page visual QA.

## Evidence Boundary

- Fixed utility is verified for five datasets, three seeds, N=1000, and ten
  windows at epsilon 5 and tau 2.
- The Docker launcher records 15/15 execution pass, but scale latency and
  throughput remain unverified until the strict aggregate validates all 15 unit
  receipts and their manifest/launch bindings.
- Simulated reviewer reports are internal quality control only.
- The checked-in Groth16 setup is a development reproducibility artifact, not a
  production ceremony.

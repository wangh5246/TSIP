# TDSC Final-Scale Adversarial Self-Review

Review date: 2026-07-22. Canonical manuscript: `TSIP/main.tex`. This review is
an internal quality-control record, not independent peer review. Its scientific
status is **final-polish verified**: the fixed five-dataset utility, strict
15-unit evaluated-circuit aggregate, mechanism-adapter boundary, small-sample
statistical boundary, exact RQ1 mutation count, user-disjoint RQ3 evaluation,
external ESA filtering rules, hardware disclosure, manuscript claim contract,
final clean build, all-page visual QA, and canonical/mirror consistency all pass.
Only author-owned release and submission declarations remain open.

## Submission Verdict

- Scientific writing and claim-evidence alignment: **pass**.
- Five-dataset fixed utility at N=1000: **pass**, with the small Porto and
  Synthetic gains disclosed rather than generalized or presented as
  statistically significant.
- Comparison semantics: **pass**. The generic external ESA and EIFFeL-style
  comparisons are identified as mechanism-level adapters, not native upstream
  deployments. Figure 5 now states the ESA sampling, shuffling, raw-count
  threshold 3, debiasing, and no-trajectory-rejection rules.
- RQ1 and RQ3 reproducibility: **pass**. RQ1 reports 12 deterministic payload
  mutations with a 2/5/5 category split. RQ3 uses a StandardScaler plus 32/16
  MLP and reports a 700/300 user-disjoint session split with exact four-dataset
  AUC values.
- Hardware and software setup: **pass**. The manuscript records the Apple M4
  host, 16 GB host memory, 10-CPU/8.22-GB Docker allocation, two concurrent
  jobs, and the passing Python, Node.js, Circom, snarkjs, and Docker versions.
- Evaluated N=1000 Docker scale evidence: **pass with an explicit performance
  boundary**. All 15 functional units verify; 13 timing-eligible units
  average 1.000 $\pm$ 0.069 proofs/s and 4.183 $\pm$ 0.248 hours per unit. Rome
  seed 101 and Synthetic seed 101 remain in functional totals but are excluded
  only from timing after documented host suspension.
- Final paper build and visual inspection: **pass**.
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

Build and inspection results from the reviewer-version audit checkpoint:

- Abstract: 148 words; manuscript checker issues: 0.
- Biber: 90 citekeys; warnings/errors: 0.
- PDF: 18 pages, US letter, PDF 1.7.
- Undefined citations/references, fatal errors, rerun requests: 0.
- Overfull boxes, LaTeX warnings, package warnings: 0.
- Underfull boxes: 40. All 18 pages were freshly rendered and inspected. There
  is no clipping, overlap, missing figure, or unreadable table/text.
- SHA-256: `main.tex` `32c5e384c121fac330f7f0bcf9f27ba1b08fbec4aa75ce2756e5232d86416b09`;
  `reference.bib` `c1c4d078c2e2acf21a204312d2f62bb2a0e71b96e17b50926d35d11ededfb6cf`;
  `main.pdf` `907e198430ea3a304725e0a4549f1611f891db327ec08cf87f17a1169afb6699`;
  `fig_eval_boundary_leakage_column.pdf`
  `34d618e07a4ffc05c9d91987d7279f9ae7f64a032245202f9000c40a362ebf86`;
  `v4_fixed_utility_heatmap.pdf`
  `97f40b9ecc6836afba59723fc9ef2d687c8c5f4702032e452adf267eceaf5386`;
  `tab_v4_fixed_utility.tex`
  `a65630598c9520f215d39dfdcbfe89c945642dcaf9e50d255a0dac6bcf123118`.
- Canonical and Heatmap paper-mirror `main.tex`/`reference.bib` files are
  byte-identical.

## Reviewer-Facing Version Audit

The extracted final PDF text contains no `V1`, `V2`, `V3`, or `V4` iteration
labels. It also contains no old/new-version comparison, correction history,
legacy or archived benchmark narrative, internal review record, release TODO,
or submission TODO. RQ6 now reports only the evaluated Groth16 relation and the
validated five-dataset scale matrix.

Source-only identifiers such as `VFour*` evidence macros, `tab_v4_*` labels,
figure filenames, and IEEE template-version comments remain because they do not
render. The manuscript checker masks non-rendered LaTeX arguments before
applying the reviewer-facing version gate, and its regression tests cover both
visible failures and source-only safe cases. Bibliographic phrases such as
`Internet-Draft` and `Cryptology ePrint Archive` are publication metadata, not
internal manuscript versions.

## Claim-Evidence Closure

`TSIP/CLAIM_EVIDENCE_MAP.md` contains 25 active major claims: 16 `supported`, seven
`analytical`, two `assumption`, zero `partial`, and zero `unsupported`. CE01 is
closed by the source-level citation audit. CE26 is closed by the Heatmap
artifact index and executable rerun contract. The earlier MDS/EETS analogy was
removed: CE25 now states administrative separation as an explicit assumption,
not as evidence that operators will not collude. CE23 is closed by aggregate
SHA-256 `2ad8e35340d0646c3b0e130468f9a00c5b66e433bedf4411929fe9f166516a95`
and enters the manuscript only through generated evidence, macros, and table.
CE11 now records the exact 12 payload mutation attempts. CE18 now binds the
four real-input AUC values to a user-disjoint RQ3 artifact.

## Five-Dimension Review

Statuses are `pass`, `needs revision`, or `needs new experiment`. A pass means
the manuscript's scoped claim is supported; it does not turn an excluded threat
or assumption into a guarantee.

| Dimension | Skeptical reviewer question | Status | Evidence and disposition |
|---|---|---|---|
| Contribution | What new knowledge is delivered? | pass | The paper isolates the hidden trajectory/payload same-primary composition gap and defines one stateful admission relation that closes it. |
| Contribution | Is the failure case meaningful rather than syntactic? | pass | A valid trajectory proof can otherwise be paired with routed payload material for another primary; the separation lemmas and A6 ablation identify the missing equality. |
| Contribution | Is novelty scoped honestly? | pass | The paper claims a new admission property and system composition, not a new SNARK, DP mechanism, physical-location proof, or general poisoning defense. |
| Contribution | Are empirical gains exaggerated? | pass | All five fixed-protocol deltas are reported; +0.007 on Porto and Synthetic is explicitly called small, and the three-seed observations are not presented as statistical significance. |
| Writing clarity | Can the relation and protocol be reproduced? | pass | Method fields, C1-C21, integer semantics, state transition, timing, warmup, the 12 RQ1 mutations, RQ3 classifier and split, hardware and software versions, artifact paths, commands, and pass criteria are explicit. |
| Writing clarity | Are terminology and evidence layers stable? | pass | SHTPC is the visible term; the evaluated relation, fixed utility, protocol smoke, and scale execution are kept non-interchangeable. The reviewer-facing paper has no internal iteration labels or drafting notes. |
| Writing clarity | Does paragraph flow support the paper story? | pass | The reverse outline maps each core prose paragraph to one topic sentence, role, and claim set, including separate functional and timing messages for scale execution. |
| Experimental strength | Are results consistent across inputs and seeds? | pass | The fixed configuration has a positive SHTPC-minus-adapter Jaccard delta for every dataset mean and for each of the 15 observed dataset-seed pairs; means and standard deviations are reported, while three seeds are treated as insufficient for a significance claim on the small gains. |
| Experimental strength | Is absolute utility hidden when it is low? | pass | Absolute Jaccard spans 0.135 to 0.878; the manuscript reports each value and does not claim uniformly high utility. |
| Experimental strength | Are failure cases visible? | pass | User-disjoint session-linking AUC remains 0.7268 to 0.7491 across the four real inputs. In-envelope pollution, false genesis, transfer, collusion, and development-setup limits also remain visible. |
| Experimental strength | Is evaluated-circuit cost established? | pass | Fifteen functional units and 225,000 generated/verified proofs pass with zero failures; 13 timing-eligible units report all-unit and per-dataset mean/sample-standard-deviation statistics, with both exclusions disclosed. |
| Evaluation completeness | Are key mechanisms ablated? | pass | No-ADWC, No-Payload-Bind, Stateful-ContextCommit, and No-Admission-Check expose the predicates responsible for A3 and A6. |
| Evaluation completeness | Is the main comparison fair? | pass | One epsilon/tau pair, N=1000, ten windows, 10% A1, and seeds 101/202/303 are fixed across all five datasets; tuned settings are excluded from the headline. |
| Evaluation completeness | Are datasets and evidence layers broad enough? | pass | Four real trajectory-derived inputs and one generated stress input are used; utility, smoke, and scale answer separate questions. |
| Evaluation completeness | Are baseline claims bounded? | pass | The external ESA comparison is explicitly a mechanism-level Nebula-style adapter. Its exact filter and debiasing rules are disclosed. VDAF, TEE, and proof-of-location systems remain analytical design points rather than falsely comparable implementations. |
| Method soundness | Are assumptions explicit and falsifiable? | pass | SRV-TS, SCS, CA3, setup, hash, channel, and non-collusion assumptions are stated with adjacent failure consequences. |
| Method soundness | Does one relation actually bind routed payload to trajectory state? | pass | C17-C21, route/binder negative fixtures, Aggregator validation, and the evaluated 22-check gate cover the stated interface. |
| Method soundness | Does the design overclaim source authenticity or robustness? | pass | The claim begins post-enrollment and excludes physical presence, metadata elimination, fully in-envelope false reports, and malicious-Shuffler state forks. |
| Method soundness | Is net benefit supported at paper scale? | pass | CE23 verifies proof/route totals, all 150 reconstructions and DP releases, and evaluated-relation timing. The paper characterizes the 4.183-hour mean unit runtime as reproducible execution rather than interactive performance. |

No additional utility or scale rerun is required by this review. The strict
validator found all 15 functional units valid and retained at least two
timing-eligible units per dataset. All machine-verifiable manuscript gates are now
closed; the remaining work is limited to author-owned release and submission
declarations.

## Completed Final-Scale Work

1. Validated all five datasets times three seeds against the expected matrix,
   current manifest hash, launch-plan/status hash, N=1000, six warmup rounds,
   ten evaluation rounds, and `state=pass`.
2. Required 16 completed rounds per unit, zero unit/round failures, complete
   proof-generation and proof-verification accounting, A/R totals of 1000/1000
   in every evaluation round, successful reconstruction, and successful DP
   release.
3. Hash-bound every validated unit record and emitted deterministic aggregate
   JSON, CSV, and LaTeX artifacts with all-unit and per-dataset mean, standard
   deviation, min/max, and throughput statistics; the manuscript does not report
   only the best seed.
4. Bound the strict aggregate into `paper_evidence.json`, updated CE23 and RQ6
   only from generated macros/tables, and kept protocol-scale results separate
   from original-input RQ5 utility.
5. Re-ran 265 focused evidence, figure, RQ3 split, and manuscript-contract tests, then
   completed the clean LaTeX/Biber build, warning scans, canonical/mirror byte
   comparison, and all-page visual QA.

## Evidence Boundary

- Fixed utility is verified for five datasets, three seeds, N=1000, and ten
  windows at epsilon 5 and tau 2. The headline comparison is against
  a mechanism-level external ESA adapter in the shared harness. It uses raw-count
  threshold 3 after sampling and shuffling. All 15 observed paired
  differences favor SHTPC, but the paper makes no statistical-significance
  claim for the small Porto and Synthetic gains.
- RQ3 session linking uses 700 training users and 300 unseen test users. Each
  seed has 1,400 balanced training pairs and 600 balanced test pairs. Mean AUC
  is 0.7434, 0.7491, 0.7268, and 0.7316 on T-Drive, GeoLife, Porto, and Rome.
  The deterministic summary SHA-256 is
  `2cd2fbb87575a5540d341fa6525a561c85541d584ef0f160987a76298df9621f`.
- The strict aggregate verifies 15/15 functional units, 225,000 generated
  and verified proofs, zero proof failures, A/R totals of 150,000/150,000, and
  150/150 reconstruction and DP-release passes. Timing uses 13 units after
  two host-suspension exclusions and remains a prototype performance result.
- The checked-in Groth16 setup is a development reproducibility artifact, not a
  production ceremony.

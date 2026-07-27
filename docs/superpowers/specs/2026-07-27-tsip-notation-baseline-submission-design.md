# TSIP Notation, Baseline, and Submission-Readiness Design

Date: 2026-07-27

## Objective

This revision prepares the TSIP manuscript for submission in one integrated pass. It will:

1. Add a compact MAIN NOTATIONS AND THEIR DESCRIPTIONS table.
2. Reduce symbol density and reserve distinct notation for the core protocol objects.
3. Remove the circuit-constraint-detail subsection while preserving the unified-relation argument.
4. Add executable, same-hardware baselines that isolate the cost and benefit of unified verification.
5. Rebuild the evaluation into a four-and-a-half-page evidence section with no theory exposition.
6. Improve paragraph length, sentence structure, figure density, and page use under the Wang Yingjie writing rules.
7. Keep all non-reference material within 15.5 pages so that references may begin in the second column of page 16.

The revision is bounded by previously approved repairs. Rectangularity will not be presented as a new mathematical theory. Unsupported compiler claims will remain removed. The rectangularity corollary will retain its non-empty-domain condition. Context authentication will remain conditional. Games 2 and 3 will remain closed under their stated assumptions. Mastic, Whisper, and Secure Stateful Aggregation will be acknowledged precisely rather than treated as interchangeable systems.

## Frozen Paper Argument

The manuscript will advance one central argument:

> In stateful private heatmap aggregation, SHTPC binds the primary cell derived from accepted hidden state to the payload that is validated and reconstructed. This claim is supported by a necessary composition condition, a unified relation, matched A6 experiments, and same-hardware comparisons. It is bounded to post-enrollment integrity and to the assumptions stated for Game 3.

Every section must support this argument. Material that does not define the problem, establish the condition, instantiate the relation, delimit the security claim, or test the resulting prediction will be shortened, moved to the artifact, or removed.

## Terminology Ledger

The following terms are canonical throughout the manuscript:

- proof-to-payload gap
- same-primary consistency
- cross-role semantic closure
- fingerprint payload bridge
- Natural-Composition
- Report-Local ZK + Prio3
- Proof-Bound Prio3
- Direct Unified-Vector
- Trusted Bridge + Prio3
- SHTPC-Full

The following formulations are disallowed:

- compiler gap and semantic compiler
- statements that describe the composition issue as a vulnerability in Prio3, EIFFeL, Whisper, or Mastic
- statements that describe adapted baselines as native reproductions of EIFFeL or Whisper
- claims that rectangularity is a new mathematical theory
- unconditional context-authentication claims
- strong modal language such as must or can when a factual, conditional, or measured statement is available

## Main Notation Design

The notation table will appear immediately after the opening of the Report and Admission Model. It will occupy one column and approximately 0.4 page.

| Symbol | Canonical description |
| --- | --- |
| uid | enrolled actor identifier |
| t | report index |
| w | aggregation window |
| x_t | reported coordinate, typeset as a bold two-dimensional vector |
| p_t | primary cell derived for report t |
| K | permitted state-window length |
| c_t | hidden state counter |
| eta_t | state transition witness or auxiliary state |
| u_t | aggregation input vector, typeset as a bold vector |
| P_t^A, P_t^R | admission-side and report-side primary commitments |
| I_w | accepted report-index set for window w |
| h_w | reconstructed heatmap, typeset as a bold vector |
| O_w | released aggregate output |
| L_S | leakage function for server S |

Coordinate notation will always be x_t = (x_t, y_t), with the coordinate object typeset in bold in LaTeX. The primary cell will always be p_t. ADWC will stop using p_i for a position or coordinate. Implementation field names will not enter the theory notation.

Local fingerprint symbols such as alpha, phi_A, phi_R, B_A, and B_R will be defined once near the bridge construction. They will not be included in the main notation table. Temporary proof-game variables will be introduced locally and retired at the end of the proof.

## Method Restructuring

The active Circuit Constraint Details subsection will be deleted in full, including the constraint inventory table, integer bit widths, low-level range checks, and mutation-test discussion. The preceding circuit subsection will remain and will state only:

1. the semantic jobs enforced by the unified relation
2. the fixed state-window parameter K = 6 used by the implementation
3. the aggregate constraint count needed to interpret the evaluation
4. the fingerprint payload bridge in one equation and one plain-language explanation
5. a pointer to the artifact for the complete circuit and test inventory

C1 through C20 will no longer serve as the narrative spine. C21 will be renamed the fingerprint payload bridge and used only where the commitment-to-payload connection is established or measured.

Definitions will be followed by a plain-language interpretation. Each theorem will be preceded by the question it resolves. Necessary conditions will be distinguished from sufficient constructions. Proofs will state their dependence on the non-empty-domain condition and the assumptions of the corresponding game.

## Prose and Paragraph Rules

The manuscript will follow these editing constraints:

- target 60 to 100 English words per paragraph
- split paragraphs longer than 110 words unless they contain an indivisible theorem or definition
- target 18 to 24 words per sentence
- split sentences longer than 32 words where meaning permits
- assign one rhetorical job to each paragraph
- prefer simple declarative sentences and passive voice or third-person subjects
- avoid we, must, can, colon, and semicolon in manuscript prose
- use consistent dash punctuation and avoid parenthetical chains
- do not repeat values that are already readable in a figure or table
- remove raw hash strings and low-level hash procedure details from the manuscript

Related work will use a capability, boundary, and relation structure. Each cited system will be described first by what it establishes, then by what its interface does not bind, and finally by how that boundary differs from the TSIP problem. Discussion and limitation material will be integrated into the Conclusion rather than restored as separate sections.

## Executable Baseline Architecture

### Oracle-Clean

Oracle-Clean is a correctness reference and not a ranked system baseline. It computes the aggregate after removing malicious reports using ground-truth labels. It establishes the attainable utility ceiling for the frozen attack matrix.

### Natural-Composition

Natural-Composition combines the existing stateful admission path with the pinned native Prio3 implementation. Admission and aggregation validate their own objects without a shared primary-binding check. It is the direct A6 control and reuses the existing pinned libprio commit.

### Report-Local ZK + Prio3

This baseline applies an EIFFeL-inspired report-local zero-knowledge filter before native Prio3 aggregation. The filter proves validity of the submitted report but does not bind the accepted state-derived primary to the aggregation encoding. The manuscript will label it as an adapted EIFFeL-style filter, not an EIFFeL reproduction.

### Proof-Bound Prio3

This baseline separates admission proof and aggregation validation while requiring both stages to share or open a primary commitment. It tests whether a modular proof-to-encoding bridge closes A6 without the full SHTPC relation. The manuscript will label the construction as Whisper-inspired proof binding, not a Whisper reproduction.

### Direct Unified-Vector

This baseline enforces the same SHTPC trajectory and primary relation but constrains the complete 10,000-dimensional one-hot vector inside the relation. It replaces the fingerprint payload bridge. Its purpose is to isolate the constraint, proving-time, and verification consequences of the bridge design.

### Trusted Bridge + Prio3

This baseline uses a plaintext or trusted checker to verify same-primary consistency before native Prio3 processing. It provides a different-trust-model performance upper bound. It will not be presented as achieving the same privacy or trust guarantees as SHTPC.

### SHTPC-Full

SHTPC-Full is the proposed unified construction with the fingerprint payload bridge and the stated post-enrollment threat model. All performance and A6 conclusions will be made relative to the matched baselines above.

Mastic will be included in related work and the baseline taxonomy as a weighted, private heavy-hitter or attribute-measurement system. It will not be forced into an executable same-primary baseline unless an interface-compatible experiment is obtained without changing the evaluated question.

## Literature Attribution Map

The manuscript and artifact will use the following source boundaries:

| System | Source-backed capability | Role in this revision | Interpretation that is excluded |
| --- | --- | --- | --- |
| Prio3 and VDAF | validates an encoded measurement under the specified aggregation circuit | pinned native aggregation component and independent-composition control | Prio3 has a same-primary defect |
| EIFFeL | supports arbitrary report or model integrity checks for secure federated aggregation | design inspiration for the report-local ZK filter | the adapted filter reproduces EIFFeL or inherits all of its guarantees |
| Whisper | provides silently verifiable proof techniques and efficient verification for large-vector aggregation | design inspiration for proof-bound encoding validation | the adapted bridge reproduces Whisper or uses its native implementation |
| Mastic | supports private weighted heavy hitters and attribute-based metrics within its protocol interface | related-work boundary and taxonomy reference | Mastic natively addresses hidden cross-stage state continuity |
| Secure Stateful Aggregation | preserves protocol-defined aggregate state across cohorts | closest stateful comparison in the scope discussion | its cohort-state semantics are identical to per-user trajectory continuity |

The bibliography keys already present in the manuscript are Barnes2026VDAF, Chowdhury2022EIFFeL, Rathee2024Whisper, Mouris2025Mastic, and Ball2024Stateful. Before submission, each descriptive sentence will be checked against the corresponding primary paper or standard. Adaptation-specific claims will cite the artifact rather than the source system.

## Baseline Fairness Contract

Every measured baseline must pass three gates before its timing is admitted:

1. honest inputs are accepted and yield the expected aggregate
2. the registered A6 behavior matches the baseline interface and stated trust model
3. the receipt records source commit, binary digest, configuration digest, input digest, hardware, and command line

Simulated cryptographic timing is inadmissible. Native implementations will be used where available. Adapted constructions will be named as adaptations and documented sufficiently for independent reconstruction. Shared code paths will be reused for actor fixtures, reports, Prio3 processing, timers, and receipt generation.

## Experiment Section Architecture

The experiment section receives a maximum of 4.5 pages. It validates claims established earlier and contains no new theorem, proof, security definition, or theoretical argument.

### Setup

Setup will consist of four visually separated paragraphs with these exact labels:

1) Datasets.

2) Comparing Baselines.

3) Evaluation Indicators.

4) Configuration.

Datasets will name the four datasets, the common preprocessing unit, the frozen train or replay split, and the role of the synthetic or controlled trace. Comparing Baselines will group reference, composition, bridge, direct-vector, trusted, and proposed variants. Evaluation Indicators will define utility, rejection, proof cost, verification cost, communication, and throughput without formulas already defined earlier. Configuration will state the Apple M4 environment, K = 6, the 10,000-cell domain, the pinned implementation versions, one warm-up, and at least 30 measured repetitions.

### Integrity and Utility

The utility matrix remains frozen. The combined robustness figure will carry dataset-level details. The prose will report only the cross-dataset trend, honest-input retention, and the wider GeoLife uncertainty when statistically supported. Dataset-specific values visible in the figure will not be restated.

### A6 Closure

One compact table will report honest acceptance and A6 rejection for all applicable baselines. The text will identify which interface accepts the mismatched primary and which bridge rejects it. This subsection verifies the same-primary prediction. It will not re-explain the theorem.

### Unified Verification Cost

The central performance table will compare constraints, proving time, verification time, bytes, throughput, and A6 rejection on the same hardware. Direct Unified-Vector isolates the fingerprint design contribution. Proof-Bound Prio3 isolates the value of full unification. Trusted Bridge separates cryptographic cost from the cost of the consistency check.

### Scaling

The existing system-scaling results will remain in compact form. Worker counts 1, 2, and 4 will be reported using the same actor and report fixture. Explanatory prose will be limited to the dominant scaling trend and any measured bottleneck.

## Figure Design

The four dataset plots will be replaced by one double-column, two-panel figure.

Panel a will use one set of axes. Method will be encoded by color and dataset by marker shape. Direct endpoint labels will be used where they do not overlap. The legend will remain compact and shared.

Panel b will present a dataset by attack-strategy contamination-gap heatmap. A shared color scale and explicit zero reference will make failure and recovery patterns visible without repeating numbers in prose.

All exported plots will use vector PDF where possible, embedded fonts, submission-size labels, and line widths that survive half-column reduction. Raster elements will be exported at no less than 600 dpi. Each subpanel must remain readable at its final printed size.

## Performance Table Design

The unified baseline table will use these columns:

| Scheme | Same-primary | Trust | Constraints | Prove ms | Verify ms | Bytes | A6 reject |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |

Mean, p50, and p95 will be reported in the table or its caption according to space. Verification p95 is mandatory because the principal systems question concerns verifier overhead. Prover throughput at 1, 2, and 4 workers may be placed in a compact adjacent panel if the table becomes too wide.

No row will contain a measured number until its fairness receipt passes. Oracle-Clean will be visually separated and will contain dashes for cryptographic cost. Trusted Bridge will carry an explicit different-trust-model label.

## Page Budget

The target allocation is:

| Component | Change |
| --- | ---: |
| notation table | +0.4 page |
| deletion of circuit details | -0.7 page |
| paragraph and redundancy compression | -0.8 page |
| merged robustness figure | -0.5 page |
| executable baseline table and analysis | +1.0 to +1.3 pages |

The expected net change is no more than +0.3 page. The main text, figures, appendices embedded in the submission, and Conclusion must end within the first column of page 16. References may begin in the second column of page 16.

If the page target is exceeded, content will be reduced in this order:

1. repeated numeric narration
2. low-level implementation detail already present in the artifact
3. redundant related-work descriptions
4. secondary scaling prose

Core claims, assumptions, baseline definitions, negative results, and uncertainty reporting will not be removed to recover space.

## Experiment Execution Stages

Execution will follow bounded stages:

1. Report-Local ZK + Prio3, with a budget of six implementation and diagnostic attempts.
2. Proof-Bound Prio3, with a budget of eight attempts.
3. Direct Unified-Vector and Trusted Bridge + Prio3, with a combined budget of ten attempts.
4. Fair performance runs, receipts, merged figures, and table generation, with a budget of six attempts.

Each stage must pass its correctness and A6 gate before performance collection begins. Existing utility experiments will not be rerun solely because of prose, notation, or layout changes. They will be rerun only if the evaluated input, attack implementation, admission decision, aggregation path, or metric definition changes.

## Error Handling and Stop Conditions

The following rules apply during implementation:

- a failed compile receives one isolated diagnostic pass before another design attempt
- a baseline that fails the fairness contract is excluded from performance comparison until corrected
- simulated timing is never substituted for an unavailable cryptographic measurement
- an adaptation must be describable reproducibly and must not inherit guarantees from the source system by name
- existing experiment outputs remain frozen when only presentation code changes
- a figure is regenerated from source data rather than edited manually

User direction will be requested if Direct Unified-Vector does not compile within its attempt budget, if an executable adaptation requires a materially different trust model from the approved row, or if the 15.5-page target remains unmet after the ordered redundancy cuts.

## Verification

The revision is complete only after the following checks pass:

1. baseline unit tests and honest-aggregate checks
2. circuit compilation, proof generation, and proof verification
3. native Prio3 verification on the pinned implementation
4. A6 acceptance or rejection checks matched to every baseline interface
5. complete receipts for every reported measurement
6. figure QA at final print size and strict source-data consistency checks
7. LaTeX and Biber compilation without undefined references, missing citations, or material overfull boxes
8. PDF audit for paragraph length, prohibited modal language, punctuation, font embedding, and page placement
9. confirmation that references begin no earlier than the second column of page 16
10. claim-to-evidence audit for every novelty, comparison, and security-boundary statement

## Deliverables

Implementation will produce:

- revised main.tex and submission PDF
- the main-notation table and notation-consistency audit
- four adapted executable baselines with tests and receipts
- a Direct Unified-Vector versus fingerprint-bridge comparison
- the merged robustness figure and its source CSV files
- the unified baseline performance table
- an updated citation and claim audit
- updated P0 through P11 extension gates recording the new baseline and layout checks

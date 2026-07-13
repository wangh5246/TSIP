# SHTPC Claim-Evidence Map

Evidence snapshot: 2026-07-13. The canonical manuscript is `TSIP/main.tex`.
The N=1000 Docker scale result remains `partial` until a strict aggregate binds
all 15 distinct unit receipts to the current manifest and launcher hashes.
Unless a path starts with `TSIP/`, experiment paths below are relative to
`TSIP_heatmap_version/runtime/experiments-heatmap/`.

## Abstract Five-Message Outline

1. Problem significance: managed heatmaps need pre-aggregation admission without revealing coordinates or primary cells.
2. Missing same-relation binding: separate trajectory and payload checks do not prove equality of their hidden primary cells.
3. SHTPC mechanism: one stateful Groth16 relation binds accepted state, window reachability, derived primary, and routed payload commitments.
4. Verified evidence: the manifest-bound circuit facts, 22 static checks, and fixed five-dataset three-seed utility comparison are complete.
5. Scoped limitation: SHTPC does not prove physical presence, hide all metadata, or reject fully in-envelope false reports.

## Claim-Evidence Map

Allowed statuses are `supported`, `partial`, `analytical`, `assumption`, and
`unsupported`. This revision contains no retained `unsupported` claim.

| ID | Claim | Manuscript location | Evidence artifact | Status | Action |
|---|---|---|---|---|---|
| CE01 | Managed private heatmaps motivate admission with coordinate and primary-cell hiding. | Abstract; Introduction opening | `TSIP/reference.bib` keys `Zheng2010GeoLife`, `Yuan2010Tdrive`, and private-aggregation references | partial | Keep the scoped motivation; complete source-level citation audit in Task 7. |
| CE02 | Separate hidden-trajectory and payload checks do not imply same-primary equality. | Abstract; Introduction gap; composition-gap lemmas | Separation lemmas and composition matrix in `TSIP/main.tex` | analytical | Keep as the paper's central logical gap. |
| CE03 | SHTPC binds accepted predecessor state, window reachability, hidden-primary derivation, and routed payload commitments in one relation. | Abstract; Introduction; Method | `docker_v4_smoke/manifest.json`; paper circuit, bindings, client, and shuffler hashes in that manifest | supported | Keep terminology and relation boundary stable. |
| CE04 | The current paper relation has 3,547 constraints, 16 public inputs, and 25 private inputs. | Abstract; Method; Security; RQ6; Conclusion | `docker_v4_smoke/analysis_v4/paper_evidence.json`; `docker_v4_smoke/manifest.json` | supported | Cite only through generated `VFour*` macros. |
| CE05 | All 22 manifest-bound static compatibility and tamper checks pass. | Abstract; RQ6 | `docker_v4_smoke/static/gate_status.json`; hash-bound in `paper_evidence.json` | supported | Keep; do not generalize to production security. |
| CE06 | The clean manifest-bound protocol path passes on five datasets. | RQ6; Artifact section | `docker_v4_smoke/protocol_clean_five_dataset_v2/suite_status.json`; hash-bound in `paper_evidence.json` | supported | Describe as protocol smoke, not original-input utility. |
| CE07 | At fixed epsilon 5 and tau 2, three-seed N=1000 SHTPC Jaccard exceeds Nebula on all five datasets, with FRR 0 and MRR 1. | Abstract; RQ5 | `docker_v4_smoke/utility/three_seed_n1000/fair_fixed_comparison.json`; companion `status.json`; generated table and figure | supported | Retain all five deltas and keep the Porto and Synthetic gains explicitly small. |
| CE08 | SHTPC does not prove physical presence, eliminate metadata leakage, or reject fully in-envelope false reports. | Abstract; Introduction scope; Discussion; Conclusion | Threat-model boundary, Game 3 leakage definition, and RQ3/RQ4 artifacts | analytical | Keep visible in first and final impressions. |
| CE09 | SRV-TS, SCS, CA3, non-collusion, setup soundness, and cryptographic assumptions are required. | Method threat model; Security; Discussion | Explicit assumptions and theorem premises in `TSIP/main.tex` | assumption | Keep assumptions explicit; do not present them as measured guarantees. |
| CE10 | The implementation maintains accepted-state continuity and validates timing and transport context before forwarding. | Method overview, threat model, protocol operations | Manifest-bound client/shuffler sources; five-dataset protocol suite status | supported | Keep as implementation behavior under the stated Shuffler model. |
| CE11 | C17-C21 reject modeled proof-to-payload and route-binding substitutions. | Method circuit; RQ1 | `docker_v4_smoke/static/gate_status.json` and its negative fixtures | supported | Keep scoped to enumerated mutations. |
| CE12 | Envelope-admission soundness follows under the theorem's knowledge-soundness, collision-resistance, timing, and state assumptions. | Security Game 1 | Theorem and reduction in `TSIP/main.tex` | analytical | Keep conditional language and avoid physical-truth wording. |
| CE13 | End-to-end same-primary payload consistency follows under the theorem's proof, digest, transport, and Aggregator-validation assumptions. | Security Game 2 | Theorem in `TSIP/main.tex`; static negative fixtures | analytical | Keep as internal consistency, not source authenticity. |
| CE14 | Coordinate and primary hiding is claimed only for equal-leakage worlds and allowed single-server corruptions. | Security Game 3; Discussion | Hybrid argument and explicit leakage function in `TSIP/main.tex` | analytical | Keep equal-`L_S` and non-collusion qualifiers adjacent to the claim. |
| CE15 | The public heatmap DP claim does not cover Shuffler metadata. | Problem definition; Method DP layer; Discussion | DP mechanism definition and cited DP results; explicit `L_S` boundary | analytical | Retain; verify high-risk DP citations in Task 7. |
| CE16 | SHTPC-Full rejects the modeled A1, A2a, A3, A5, and A6 violations while mechanism ablations expose their missing checks. | RQ1 | `baseline_tsip_A1_summary.csv`, `baseline_tsip_A2a_summary.csv`, `baseline_tsip_A3_summary.csv`, `baseline_tsip_A5_summary.csv`, `baseline_tsip_A6_summary.csv`; static gate | supported | Keep the word `modeled`; do not broaden to arbitrary attacks. |
| CE17 | Stateful context alone still admits A6, while measured envelope checks expose sharp policy boundaries. | RQ2 | `full_n1000_rq/rq1/contextcommit_admission_summary.csv`; `full_n1000_rq/rq2/*_boundary_results_summary.csv` | supported | Keep baseline definition and parameterization visible. |
| CE18 | Shuffler-visible timing and chain metadata support behavior inference despite coordinate hiding. | RQ3; Discussion | `full_n1000_rq/rq3/real_metadata_four_real/real_metadata_summary.csv`; `rq3/synthetic_membership_n1000/metrics.json` | supported | Keep as residual leakage, not a coordinate-recovery result. |
| CE19 | Payload-consistent, in-envelope malicious reports can remain admissible and can pollute hotspots. | RQ4; Discussion | `full_n1000_rq/rq4/*/hotspot_pollution_summary.csv`; `in_envelope_heatmap_bias_summary.csv`; joint-adaptive summary | supported | Keep as a residual-risk result and separate external mitigations. |
| CE20 | The legacy GeoLife epsilon sweep separates admission behavior from post-admission utility. | RQ5 supporting paragraph | Existing utility sweep receipts | supported | Keep subordinate to CE07; do not use it as the headline utility comparison. |
| CE21 | Archive compatibility (2,728/14/23), historical performance (3,056/14/23), and current paper (3,547/16/25) are distinct relations. | RQ6 | `V4_METHOD_AUDIT.md`; `circuit_bench/20260504_v4/circuit_perf.csv`; current manifest and evidence JSON | supported | Never transfer measurements across layers. |
| CE22 | The 2026-05-04 snarkjs timings and 128-byte proof object belong only to the historical 3,056 relation. | RQ6 | `circuit_bench/20260504_v4/circuit_perf.csv` | supported | Keep explicitly historical; omit unreceipted 5,694-byte frame claim. |
| CE23 | Current three-seed N=1000 latency and throughput are not yet paper-verified. | RQ6; absent from Abstract | `docker_n1000_v4/launch_status.json`; strict aggregate currently absent | partial | Update only after 15/15 unit validation and strict aggregate generation. |
| CE24 | The current Groth16 setup is a development setup, not a production ceremony. | Discussion; Artifact section | `docker_v4_smoke/manifest.json` setup field | supported | Keep this limitation in artifact and submission materials. |
| CE25 | Multi-operator governance examples make the HBC/non-collusion model plausible. | Method threat model | Cited MDS/EETS governance sources | partial | Keep as examples, not proof; verify primary sources in Task 7. |
| CE26 | The artifact exposes enough interface and receipt material to audit the proof-to-payload boundary. | Artifact section | Manifest, evidence builder, static/protocol/utility receipts | partial | Complete the Heatmap-specific artifact index and exact rerun commands in Task 7. |
| CE27 | SHTPC is suitable for managed deployments but not anonymous or fully untrusted-Shuffler settings. | Discussion; Conclusion | Consequence of CE08, CE09, CE14, CE18, and CE19 | analytical | Keep as deployment guidance, not a universal recommendation. |

## Reverse Outline

Figure/table captions, displayed equations, theorem bodies, and subsection
headings are excluded because they are not prose paragraphs. List items in the
Introduction are included because each states a separate contribution.

### Introduction

Section thesis: private heatmap admission needs same-relation binding between
the hidden trajectory-derived primary and the routed payload, under a deliberately
narrow trust and leakage boundary.

| Paragraph | Manuscript location | Topic sentence | Role | Claim IDs |
|---|---|---|---|---|
| I01 | Introduction opening | Managed private heatmap services turn enrolled-device reports into population-level spatial statistics. | Establish setting, significance, and managed-system assumptions. | CE01 |
| I02 | Proof-to-payload gap | The structural gap is a proof-to-payload gap. | State why separated hidden checks do not imply equality. | CE02 |
| I03 | Adversarial example | A concrete adversarial report illustrates the problem. | Instantiate the mismatch and motivate in-relation binding. | CE02 |
| I04 | Proposed layer | SHTPC addresses this gap as a stateful zero-knowledge admission layer. | Summarize the end-to-end mechanism. | CE03, CE10, CE11 |
| I05 | Scope | The claim is intentionally limited to post-enrollment data-plane consistency. | Bound physical truth, metadata, corruption, and in-envelope risks. | CE08, CE09, CE14, CE15 |
| I06 | Contribution 1 | This paper makes three contributions: it first formalizes SHTPC. | State the property and its explicit boundary. | CE03, CE08 |
| I07 | Contribution 2 | The second contribution designs one accepted zero-knowledge statement. | State mechanism and analytical separation results. | CE02, CE11, CE12, CE13 |
| I08 | Contribution 3 | The third contribution evaluates admission-boundary enforcement. | Preview measured violations, leakage, utility, and manifest evidence. | CE05, CE07, CE16, CE17, CE18, CE19 |

### Method

Section thesis: SHTPC inserts a stateful proof-carrying Shuffler admission step
whose commitments, circuit, timing, and downstream validation enforce the scoped
same-primary relation before aggregation.

| Paragraph | Manuscript location | Topic sentence | Role | Claim IDs |
|---|---|---|---|---|
| M01 | Method opening | SHTPC follows the Encode-Shuffle-Analyze pipeline. | Place proof-carrying admission in the system pipeline. | CE03 |
| M02 | System Overview | The overview figure shows the full pipeline. | Map proof/state verification to aggregation and DP release. | CE03, CE10, CE15 |
| M03 | System Overview | In each reporting round, a client encodes a clipped one-hot contribution. | Describe client forward processing and payload binding. | CE03, CE11 |
| M04 | System Overview | Additive secret sharing prevents either Aggregator from seeing plaintext contributions alone. | State the role-separated input-privacy mechanism. | CE09, CE14 |
| M05 | System Overview | The Shuffler maintains an append-only accepted-state log under SCS. | Define the atomic admission-to-state transition. | CE09, CE10 |
| M06 | Threat Model | The threat model considers malicious clients that may deviate arbitrarily. | Define client capabilities and public knowledge. | CE09 |
| M07 | Threat Model | The adversary may attempt violation families A1 through A6. | Map modeled violations to circuit and deployment controls. | CE08, CE16 |
| M08 | Threat Model | The server side uses separated honest-but-curious roles. | State corruption and collusion boundaries. | CE09, CE14 |
| M09 | Threat Model | Timing follows the server-issued SRV-TS assumption. | Prevent client-selected time budgets. | CE09, CE10 |
| M10 | Threat Model | SCS requires an append-only accepted-state log and atomic compare-and-swap. | Make state-consistency assumptions explicit. | CE09, CE10 |
| M11 | Threat Model | Enrollment authorization follows CA3. | Define threshold-attestation assumptions. | CE09 |
| M12 | Threat Model | SHTPC leaves ground-truth enrollment and voluntary transfer to deployment controls. | Exclude false genesis and A2b from circuit guarantees. | CE08, CE09 |
| M13 | Threat Model | Transferred credentials must still satisfy the public admission envelope. | State what remains enforced after transfer. | CE08, CE10 |
| M14 | Threat Model | Warmup raises false-genesis cost but does not restore physical truth. | Bound warmup and Aggregator-collusion claims. | CE08, CE09 |
| M15 | Threat Model | Multi-operator examples illustrate the server model's deployability. | Motivate, without proving, governance assumptions. | CE25 |
| M16 | Threat Model | The component leakage boundary is summarized by role. | Separate Shuffler metadata from Aggregator share views. | CE14, CE15 |
| M17 | Commitment Chain | The commitment chain and payload binders provide SHTPC's state-and-payload substrate. | Motivate both commitment mechanisms. | CE03, CE10, CE11 |
| M18 | Commitment Chain | Each client maintains a chain of salted location commitments. | Define hidden state representation. | CE10, CE14 |
| M19 | Commitment Chain | The paper uses explicit notation for primary, payload, and A/R binders. | Stabilize binder terminology. | CE03 |
| M20 | Commitment Chain | The chain commitment binds state, context, payload binders, and identity. | Specify chain construction and context scope. | CE10, CE11 |
| M21 | Commitment Chain | The circuit derives the primary cell and opens every payload binder to it. | State same-primary semantics. | CE03, CE11 |
| M22 | Commitment Chain | The client sends seed-compressed share material through separate ciphertexts. | Connect proof binders to transport and Aggregator checks. | CE10, CE11, CE14 |
| M23 | Commitment Chain | The privacy claim concerns the expanded aggregation view, not a wire-vector size. | Clarify representation and withhold unreceipted frame size. | CE14, CE26 |
| M24 | Commitment Chain | Each submitted report has an explicit frame and public statement. | Define report syntax, witness, and per-role validation. | CE03, CE10, CE11 |
| M25 | Commitment Chain | The identity commitment binds the enrollment secret and user identifier. | Define identity binding and off-chain authentication. | CE10 |
| M26 | Commitment Chain | The Shuffler checks continuity against the previously accepted current hash. | State client state-storage implications. | CE10 |
| M27 | Distance Circuit | The distance circuit makes SHTPC predicates one accepted statement. | State circuit motivation and advantage. | CE02, CE03, CE11 |
| M28 | Distance Circuit | The main circuit uses a compile-time window constant. | Define K6/K30 artifact parameterization. | CE21 |
| M29 | Distance Circuit | A signed timing token binds the step duration to user, epoch, and round. | Specify server-issued motion budgets. | CE09, CE10 |
| M30 | Distance Circuit | The public statement and private witness have explicit fields. | Separate visible binders from hidden coordinates and openings. | CE03, CE14 |
| M31 | Distance Circuit | Six constraint groups implement trajectory, identity, mode, and payload checks. | Map C1-C21 to their predicates. | CE03, CE11 |
| M32 | Distance Circuit | The manifest-bound paper relation compiles to generated circuit facts. | Bind Method numbers to the current R1CS receipt. | CE04 |
| M33 | Distance Circuit | C21 distinguishes SHTPC from a separated trajectory/VDAF composition. | Explain the central same-primary relation. | CE02, CE11 |
| M34 | Distance Circuit | Sharing C21 with trajectory constraints binds accepted motion to the same payload primary. | Explain why one relation is technically necessary. | CE02, CE13 |
| M35 | Distance Circuit | Circuit openings and Shuffler state jointly enforce chain equality and monotonic rounds. | Complete the state-transition argument. | CE10, CE12 |
| M36 | Enrollment and Warmup | SHTPC cannot certify the first committed location as ground truth. | Mark where the cryptographic claim begins. | CE08 |
| M37 | Enrollment and Warmup | Bootstrap and steady state use one circuit path. | Avoid a weaker warmup relation. | CE10 |
| M38 | Enrollment and Warmup | Warmup and session-break rules withhold reports while advancing valid state. | Define re-entry behavior. | CE10 |
| M39 | Differential Privacy | After admission, the Decoder applies SVT/Laplace to clipped counts. | Separate admission from release privacy. | CE15 |
| M40 | Differential Privacy | The Decoder scans cells deterministically and releases thresholded noisy counts. | Define the released object and sensitivity boundary. | CE15 |
| M41 | Protocol Operations | The steady-state path keeps admission, aggregation, and release separate. | Summarize role order. | CE03, CE10, CE15 |
| M42 | Protocol Operations | Re-enrollment returns to warmup rather than inheriting admission rights. | Define mode, tier, and epoch transitions. | CE10 |
| M43 | Protocol Operations | Server-issued timing prevents client-selected motion budgets. | Specify timing-token validation and reset behavior. | CE09, CE10 |
| M44 | Circuit Details | C1-C20 cover trajectory and encoding while C21 binds payload. | Introduce the constraint table. | CE03, CE11 |
| M45 | Circuit Details | The manifest-bound arity-3 Poseidon circuit has the generated constraint count. | Repeat the current artifact fact at implementation detail. | CE04 |
| M46 | Integer Semantics | Every ordered BN254 value is range-checked before comparison. | Exclude field-wraparound ambiguity. | CE12 |
| M47 | Binding Tests | The implementation mutates every modeled binder and route field after a valid baseline. | Summarize deterministic negative-test coverage. | CE05, CE11 |

### Evaluation

Section thesis: each RQ tests a stated admission boundary or residual risk, while
utility and artifact layers remain separate from the incomplete current scale
aggregate.

| Paragraph | Manuscript location | Topic sentence | Role | Claim IDs |
|---|---|---|---|---|
| E01 | Evaluation opening | The evaluation follows the narrowed paper claims. | Map RQ1-RQ6 and exclude general truthfulness/robustness. | CE08, CE16, CE17, CE18, CE19, CE23 |
| E02 | Experimental Setup | The dataset paragraph defines four real trajectory-derived inputs and one generated stress input. | Establish the five-dataset, no-bootstrap, N=1000 utility scope and baseline family. | CE01, CE07 |
| E03 | Experimental Setup | The boundary-violation paragraph defines suites and default configuration. | Bind modeled attacks, parameters, and metrics to receipts. | CE16, CE17, CE19 |
| E04 | Experimental Setup | The metrics paragraph defines rejection, utility, and artifact-versioning rules. | Prevent metric and circuit-layer conflation before the evidence-layer split. | CE20, CE21, CE23 |
| E05 | Experimental Setup | The original-input utility paragraph identifies the source of RQ5 values. | Bind the fixed table and figure to the five prepared inputs and three seeds. | CE07 |
| E06 | Experimental Setup | The safe-trajectory paragraph isolates the clean Docker protocol smoke. | State what the smoke exercises and why it is not utility evidence. | CE05, CE06 |
| E07 | Experimental Setup | The full-scale paragraph defines the 15-unit Groth16 matrix. | Separate current protocol execution evidence from original-input utility and withhold unverified performance. | CE23 |
| E08 | RQ1 | RQ1 asks whether SHTPC rejects proof/payload-inconsistent reports. | State target attack and ablation purpose. | CE11, CE16 |
| E09 | RQ1 | SHTPC-Full rejects all modeled A1, A2a, A3, A5, and A6 violations. | Report scoped ablation result and mechanism attribution. | CE16 |
| E10 | RQ1 | A6 is also tested with private binder, blob, route, and replay mutations. | Connect table-level evidence to static end-to-end negatives. | CE05, CE11 |
| E11 | RQ2 | RQ2 asks how statefulness affects predecessor, replay, and window consistency. | Compare context-only state to in-relation primary equality. | CE17 |
| E12 | RQ2 | Boundary sweeps separate per-step and window continuity predicates. | Explain transition locations without changing policy semantics. | CE17 |
| E13 | RQ2 | A3 is evaluated as a parameterized ADWC admission check. | Report K6/K30 sensitivity and deployment recommendation. | CE17 |
| E14 | RQ2 | The tau/tau2 sweep checks DP-parameter invariance and session withholding. | Separate admission verification from DP settings. | CE17, CE20 |
| E15 | RQ3 | RQ3 asks what remains inferable from Shuffler-visible leakage. | Report metadata inference and preserve the leakage boundary. | CE18 |
| E16 | RQ4 | RQ4 asks what remains after the cryptographic envelope is enforced. | State bounded influence but not ground-truth defense. | CE08, CE19 |
| E17 | RQ4 proposition | Accepted malicious mass and support are bounded by clipping and reachability. | Provide an analytical influence bound. | CE19 |
| E18 | RQ4 joint adversary | SHTPC enforces an envelope, not ground truth. | Report payload-decoupled rejection and in-envelope acceptance. | CE19 |
| E19 | RQ5 | RQ5 fixes one five-dataset utility protocol without per-dataset retuning. | Define N=1000, ten rounds, three seeds, epsilon 5, tau 2, 10% A1, and top-50 Jaccard. | CE07 |
| E20 | RQ5 | SHTPC has five positive Jaccard deltas over Nebula under the fixed protocol. | Report every absolute value and distinguish large gains from the small Porto and Synthetic gains. | CE07, CE20 |
| E21 | RQ6 archive layer | RQ6 begins by identifying non-interchangeable evidence layers. | Restrict archive compatibility to saved witness validation. | CE21 |
| E22 | RQ6 historical layer | The 2026-05-04 receipt belongs to a distinct historical relation. | Retain only receipted historical timings/proof size. | CE21, CE22 |
| E23 | RQ6 current layer | The current manifest-bound relation has generated circuit facts and passing gates. | State current evidence and withhold latency/throughput pending strict aggregate. | CE04, CE05, CE06, CE23 |

### Discussion

Section thesis: the measured and analytical guarantees depend on explicit trust,
leakage, setup, and governance boundaries that constrain suitable deployments.

| Paragraph | Manuscript location | Topic sentence | Role | Claim IDs |
|---|---|---|---|---|
| D01 | Discussion opening | The TCB consists of setup, enrollment keys, channels, and hash assumptions. | Summarize corruption and setup consequences. | CE09, CE24 |
| D02 | Metadata | Metadata is an intentional boundary rather than an implementation artifact. | Explain operational value and surveillance risk of `L_S`. | CE15, CE18 |
| D03 | Metadata mitigations | Several mitigations can reduce `L_S` at operational cost. | Present non-cryptographic tradeoffs. | CE18, CE27 |
| D04 | Residual attacks | SHTPC enforces an envelope, not ground truth. | Restate in-envelope, false-genesis, and transfer limits. | CE08, CE19 |
| D05 | Suitability | SHTPC is best suited to managed heatmap deployments. | Translate assumptions into deployment fit. | CE27 |
| D06 | Artifact | The proof-to-payload claim requires interface-level artifact records. | Define reproducibility contents and verification boundary. | CE26 |
| D07 | Artifact setup | Proving and verification keys are protocol artifacts. | Require regeneration after interface changes and disclose development setup. | CE24, CE26 |
| D08 | Ethics | SHTPC hides allowed single-server inputs but retains pseudonymous admission state. | State privacy benefit and governance risk together. | CE14, CE18, CE27 |
| D09 | Governance | Deployments should define consent, retention, revocation, access, and audit policies. | Give scoped operational safeguards and high-risk-use warning. | CE27 |

### Conclusion

Section thesis: SHTPC contributes a narrow same-relation admission guarantee,
supported by scoped evidence and bounded by metadata, enrollment, and in-envelope
risks.

| Paragraph | Manuscript location | Topic sentence | Role | Claim IDs |
|---|---|---|---|---|
| C01 | Conclusion | This paper formulates SHTPC as a narrow admission-consistency goal. | Restate insight, current circuit identity, evidence, and deployment boundary. | CE03, CE04, CE08, CE16, CE18, CE19, CE27 |
| C02 | Future Work | Future work should strengthen enrollment, Shuffler auditability, adaptive evaluation, and setup portability. | Route excluded risks to future work without claiming they are solved. | CE08, CE23, CE24 |

## Review Gate

- Abstract has exactly five message sentences and excludes the partial scale result.
- Every retained major claim has a non-`unsupported` status and an action.
- Historical relation measurements are not evidence for the manifest-bound paper relation.
- The fixed fair five-dataset evidence is integrated in E02 and E19-E20.
- Final-scale writing may update CE23 only after strict aggregate verification.

## Five-Dimension Adversarial Self-Review

Statuses in this checklist are `pass`, `needs revision`, or
`needs new experiment`. A `needs revision` item remains a mandatory downstream
task and is not treated as paper-ready.

| Dimension | Reviewer question | Status | Evidence or required action |
|---|---|---|---|
| Contribution | What new knowledge does the paper provide? | pass | CE02-CE03 isolate same-relation trajectory/payload binding as the contribution. |
| Contribution | Is the failure case meaningful rather than trivial? | pass | I02-I03 show a valid hidden proof can be paired with a different routed primary without the new relation. |
| Contribution | Is the idea non-obvious beyond standard composition? | pass | The separation lemmas and CE11 explain why state/context or VDAF-style checks alone do not imply equality. |
| Contribution | Is the empirical gain stated without exaggeration? | pass | Abstract and RQ5 say two of five positive Jaccard deltas are small; CE07 retains every exact value. |
| Contribution | Is at least one novelty type explicit? | pass | The paper claims a new scoped admission property and one-relation system design, not a new proof system or DP mechanism. |
| Writing clarity | Can a knowledgeable reader reproduce the method? | needs revision | Method is detailed, but Task 7 must add the Heatmap artifact index and exact rerun commands. |
| Writing clarity | Are key modules technically specified? | pass | M17-M47 cover state, binders, transport, circuit, timing, warmup, DP, and integer semantics. |
| Writing clarity | Is each module motivated by a concrete challenge? | pass | M17, M27, and M36 explicitly connect design choices to the proof/payload gap and enrollment boundary. |
| Writing clarity | Are terms and notation consistent? | pass | SHTPC terminology, generated V4 facts, and `eq:r-shtpc` are now consistent; stale current facts are absent. |
| Writing clarity | Does every core-section paragraph carry one message? | pass | The 89-entry reverse outline records one topic sentence and role per prose paragraph/list contribution. |
| Experimental strength | Are improvements over the strongest fair baseline meaningful? | pass | RQ5 reports all five deltas and distinguishes GeoLife/T-Drive/Rome gains from the small Porto/Synthetic gains. |
| Experimental strength | Is absolute performance competitive? | pass | The generated table and figure expose mean Jaccard, standard deviation, delta, FRR, and MRR under one fixed protocol. |
| Experimental strength | Are gains consistent across datasets and seeds? | pass | CE07 binds five positive mean deltas and three-seed standard deviations under one fixed configuration. |
| Experimental strength | Are strengths and failure cases reported honestly? | pass | CE08, CE18, and CE19 keep metadata and in-envelope failures visible in Abstract and Discussion. |
| Evaluation completeness | Are key design choices ablated? | pass | CE16-CE17 cover ADWC, payload binding, context-only state, and no-admission variants. |
| Evaluation completeness | Are strong baselines compared fairly? | pass | The headline uses one epsilon/tau configuration; Nebula is the strongest fixed baseline on all five inputs, and tuned results stay out of the table. |
| Evaluation completeness | Are metrics sufficient and separated by evidence layer? | pass | E04-E07 and CE20-CE23 separate rejection, utility, protocol smoke, historical microbenchmarks, and current scale. |
| Evaluation completeness | Are datasets sufficiently broad? | pass | The manuscript integrates four real trajectory-derived inputs and one explicitly generated clustered random-walk stress input. |
| Evaluation completeness | Is the protocol documented clearly? | pass | Experimental Setup separates original-input utility, safe-trajectory protocol smoke, and full Groth16 scale in three paragraphs. |
| Method soundness | Is the deployment setting realistic? | pass | CE09, CE25, and CE27 restrict the claim to managed deployments with explicit governance assumptions. |
| Method soundness | Are hidden technical defects addressed? | pass | CE05 and CE11 bind the current circuit to 22 compatibility/tamper checks and negative fixtures. |
| Method soundness | Does the fair result avoid per-dataset retuning? | pass | CE07 uses one epsilon/tau pair across all datasets; tuned results are not the headline comparison. |
| Method soundness | Are complexity and limitations visible? | pass | Discussion and CE08/CE14/CE18/CE24 expose leakage, collusion, setup, enrollment, and in-envelope limits. |
| Method soundness | Is the net benefit supported at paper scale? | needs revision | CE23 remains partial until all 15 unit receipts and the strict aggregate verify current latency/throughput. |

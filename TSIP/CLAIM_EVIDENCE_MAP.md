# SHTPC Claim-Evidence Map

Evidence snapshot: 2026-07-22. The canonical manuscript is `TSIP/main.tex`.
The N=1000 Docker scale result is `verified`: a validated aggregate binds all 15
distinct units to one evaluated circuit and execution configuration. Functional
totals include every unit; timing uses 13 eligible units after two documented
host-suspension exclusions.
Unless a path starts with `TSIP/`, experiment paths below are relative to
`TSIP_heatmap_version/runtime/experiments-heatmap/`.

## Abstract Five-Message Outline

1. Problem significance: managed heatmaps need pre-aggregation admission without revealing coordinates or primary cells.
2. Missing same-relation binding: separate trajectory and payload checks do not prove equality of their hidden primary cells.
3. SHTPC mechanism: one stateful Groth16 relation binds accepted state, window reachability, derived primary, and routed payload commitments.
4. Verified evidence: the evaluated circuit facts, 22 static checks, 225,000 scale proofs, and fixed five-dataset three-seed comparison against a mechanism-level external ESA adapter are complete.
5. Scoped limitation: SHTPC does not prove physical presence, hide all metadata, or reject fully in-envelope false reports.

## Claim-Evidence Map

Allowed statuses are `supported`, `partial`, `analytical`, `assumption`, and
`unsupported`. This map contains 25 active major claims: 16 `supported`, seven
`analytical`, two `assumption`, zero `partial`, and zero `unsupported`.

| ID | Claim | Manuscript location | Evidence artifact | Status | Action |
|---|---|---|---|---|---|
| CE01 | Managed private heatmaps motivate admission with coordinate and primary-cell hiding. | Abstract; Introduction opening | `TSIP/reference.bib` keys `Zheng2010GeoLife`, `Yuan2010Tdrive`, and private-aggregation references; `TSIP/CITATION_AUDIT.md` | supported | Source-level metadata and claim scope were audited in Task 7; keep the motivation scoped. |
| CE02 | Separate hidden-trajectory and payload checks do not imply same-primary equality. | Abstract; Introduction gap; composition-gap lemmas | Separation lemmas and composition matrix in `TSIP/main.tex` | analytical | Keep as the paper's central logical gap. |
| CE03 | SHTPC binds accepted predecessor state, window reachability, hidden-primary derivation, and routed payload commitments in one relation. | Abstract; Introduction; Method | `docker_v4_smoke/manifest.json`; paper circuit, bindings, client, and shuffler hashes in that manifest | supported | Keep terminology and relation boundary stable. |
| CE04 | The evaluated relation has 3,547 constraints, 16 public inputs, and 25 private inputs. | Abstract; Method; Security; RQ6; Conclusion | `docker_v4_smoke/analysis_v4/paper_evidence.json`; `docker_v4_smoke/manifest.json` | supported | Cite only through generated evidence macros. |
| CE05 | All 22 static compatibility and tamper checks pass. | Abstract; RQ6 | `docker_v4_smoke/static/gate_status.json`; hash-bound in `paper_evidence.json` | supported | Keep; do not generalize to production security. |
| CE06 | The clean Docker protocol path passes on five datasets. | RQ6; Artifact section | `docker_v4_smoke/protocol_clean_five_dataset_v2/suite_status.json`; hash-bound in `paper_evidence.json` | supported | Describe as protocol smoke, not original-input utility. |
| CE07 | At fixed epsilon 5, three-seed N=1000 SHTPC mean Jaccard exceeds the mechanism-level external ESA and EIFFeL-style adapters on all five datasets; all 15 observed SHTPC-minus-ESA dataset-seed differences favor SHTPC, with FRR 0 and MRR 1. | Abstract; RQ5 | `docker_v4_smoke/utility/three_seed_n1000/fair_fixed_comparison.json`; `aggregate_summary.csv`; `run_v4_utility_compare.py`; `baselines/nebula_baseline.py`; `baselines/eiffel_baseline.py`; Figure 5 | supported | Retain all five ESA deltas and the five EIFFeL-style means. State SHTPC threshold 2 separately from the ESA raw-count threshold 3 and sampling/debiasing rule. Make no statistical-significance claim for the small Porto and Synthetic differences. |
| CE08 | SHTPC does not prove physical presence, eliminate metadata leakage, or reject fully in-envelope false reports. | Abstract; Introduction scope; Discussion; Conclusion | Threat-model boundary, Game 3 leakage definition, and RQ3/RQ4 artifacts | analytical | Keep visible in first and final impressions. |
| CE09 | SRV-TS, SCS, CA3, non-collusion, setup soundness, and cryptographic assumptions are required. | Method threat model; Security; Discussion | Explicit assumptions and theorem premises in `TSIP/main.tex` | assumption | Keep assumptions explicit; do not present them as measured guarantees. |
| CE10 | The implementation maintains accepted-state continuity and validates timing and transport context before forwarding. | Method overview, threat model, protocol operations | Validated client/shuffler sources; five-dataset protocol suite status | supported | Keep as implementation behavior under the stated Shuffler model. |
| CE11 | C17-C21 reject the 12 deterministic proof-to-payload and route-binding mutation attempts. | Method circuit; RQ1 | `docker_v4_smoke/static/gate_status.json` and its negative fixtures | supported | Report the two proof/public-signal, five private-witness, and five post-proof route attempts. Each is attempted once against the passing fixture. |
| CE12 | Envelope-admission soundness follows under the theorem's knowledge-soundness, collision-resistance, timing, and state assumptions. | Security Game 1 | Theorem and reduction in `TSIP/main.tex` | analytical | Keep conditional language and avoid physical-truth wording. |
| CE13 | End-to-end same-primary payload consistency follows under the theorem's proof, digest, transport, and Aggregator-validation assumptions. | Security Game 2 | Theorem in `TSIP/main.tex`; static negative fixtures | analytical | Keep as internal consistency, not source authenticity. |
| CE14 | Coordinate and primary hiding is claimed only for equal-leakage worlds and allowed single-server corruptions. | Security Game 3; Discussion | Hybrid argument and explicit leakage function in `TSIP/main.tex` | analytical | Keep equal-`L_S` and non-collusion qualifiers adjacent to the claim. |
| CE15 | The public heatmap DP claim does not cover Shuffler metadata. | Problem definition; Method DP layer; Discussion | DP mechanism definition and cited DP results; explicit `L_S` boundary | analytical | Retain; verify high-risk DP citations in Task 7. |
| CE16 | SHTPC-Full rejects the modeled A1, A2a, A3, A5, and A6 violations while mechanism ablations expose their missing checks. | RQ1 | `baseline_tsip_A1_summary.csv`, `baseline_tsip_A2a_summary.csv`, `baseline_tsip_A3_summary.csv`, `baseline_tsip_A5_summary.csv`, `baseline_tsip_A6_summary.csv`; static gate | supported | Keep the word `modeled`; do not broaden to arbitrary attacks. |
| CE17 | Stateful context alone still admits A6, while measured envelope checks expose sharp policy boundaries and the K6/K30 drift-sensitivity tradeoff. | RQ2 | `full_n1000_rq/rq1/contextcommit_admission_summary.csv`; `full_n1000_rq/rq2/*_boundary_results_summary.csv`; `adwc_sweeps/20260417_225953/drift_k_sweep.csv` | supported | Keep baseline definition, GeoLife provenance, and K30 stress-profile qualification visible. |
| CE18 | Shuffler-visible timing and chain metadata support behavior inference despite coordinate hiding. User-disjoint N=1000 session-linking AUC is 0.7434, 0.7491, 0.7268, and 0.7316 on T-Drive, GeoLife, Porto, and Rome. | RQ3; Discussion | `full_n1000_rq/rq3/real_metadata_four_real/real_metadata_summary.csv`; `real_metadata_details.json`; `membership_inference/synth_500u_30r_delay1p5_ablation/` | supported | Preserve the StandardScaler plus 32/16 MLP configuration, the 700/300 user split, the 1,400/600 pair counts, and the residual-leakage scope. |
| CE19 | Payload-consistent, in-envelope malicious reports can remain admissible and can pollute hotspots; a controlled external detector and SHTPC address complementary failure modes. | RQ4; Discussion | `experiments-heatmap/hotspot_pollution/hotspot_pollution_summary.csv`; `full_n1000_rq/rq4/*/hotspot_pollution_summary.csv`; `in_envelope_heatmap_bias_summary.csv`; joint-adaptive summary | supported | Keep as a residual-risk result, disclose the five-seed detector parameters, and do not present the detector as a native upstream system. |
| CE20 | The GeoLife epsilon sensitivity sweep separates admission behavior from post-admission utility. | RQ5 supporting paragraph | Existing utility sweep records | supported | Keep subordinate to CE07; do not use it as the headline utility comparison. |
| CE23 | The evaluated three-seed N=1000 matrix verifies 225,000 proofs with zero failures across 15 units; 13 timing-eligible units average 1.000 $\pm$ 0.069 proofs/s and 4.183 $\pm$ 0.248 hours, with Rome/101 and Synthetic/101 excluded only from timing after host suspension. | Abstract; Experimental Setup; RQ6; Conclusion | `docker_n1000_v4/aggregate_summary.json`; `aggregate_by_dataset.csv`; generated `TSIP/tables/tab_v4_n1000_scale.tex`; hash-bound `docker_v4_smoke/analysis_v4/paper_evidence.json` | supported | Keep all functional units in totals, disclose timing $n$ per dataset, and characterize the result as reproducible execution rather than interactive latency. |
| CE24 | The evaluated Groth16 setup is a development setup, not a production ceremony. | Discussion; Artifact section | `docker_v4_smoke/manifest.json` setup field | supported | Keep this limitation in artifact and submission materials. |
| CE25 | Distinct administrative domains, access documentation, and cross-role audits are deployment requirements for the HBC/non-collusion model, not cryptographic guarantees. | Method threat model | Explicit threat-model assumptions and failure conditions in `TSIP/main.tex` | assumption | Keep as an assumption; do not use governance analogies as evidence of non-collusion. |
| CE26 | The artifact exposes enough interface and execution material to audit the proof-to-payload boundary. | Artifact section | `TSIP_heatmap_version/ARTIFACT_README.md`; manifest, evidence builder, and static/protocol/utility records | supported | Heatmap-specific paths, commands, pass criteria, data boundary, and scale limitation were indexed in Task 7. |
| CE27 | SHTPC is suitable for managed deployments but not anonymous or fully untrusted-Shuffler settings. | Discussion; Conclusion | Consequence of CE08, CE09, CE14, CE18, and CE19 | analytical | Keep as deployment guidance, not a universal recommendation. |

Claim IDs CE21 and CE22 are retired from the reviewer-facing manuscript. They
described circuit-lineage and benchmark-lineage records that support no active
paper claim. Those records remain available only for internal artifact audit.

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
| I08 | Contribution 3 | The third contribution evaluates admission-boundary enforcement. | Preview quantitative evidence from modeled violations, leakage, fixed utility, and 225,000 evaluated-circuit proofs. | CE05, CE07, CE16, CE17, CE18, CE19, CE23 |

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
| M15 | Threat Model | Independent operation can make non-collusion auditable but cannot enforce it cryptographically. | State the administrative separation, access-documentation, and audit requirements and their failure condition. | CE25 |
| M16 | Threat Model | The component leakage boundary is summarized by role. | Separate Shuffler metadata from Aggregator share views. | CE14, CE15 |
| M17 | Commitment Chain | The commitment chain and payload binders provide SHTPC's state-and-payload substrate. | Motivate both commitment mechanisms. | CE03, CE10, CE11 |
| M18 | Commitment Chain | Each client maintains a chain of salted location commitments. | Define hidden state representation. | CE10, CE14 |
| M19 | Commitment Chain | The paper uses explicit notation for primary, payload, and A/R binders. | Stabilize binder terminology. | CE03 |
| M20 | Commitment Chain | The chain commitment binds state, context, payload binders, and identity. | Specify chain construction and context scope. | CE10, CE11 |
| M21 | Commitment Chain | The circuit derives the primary cell and opens every payload binder to it. | State same-primary semantics. | CE03, CE11 |
| M22 | Commitment Chain | The client sends seed-compressed share material through separate ciphertexts. | Connect proof binders to transport and Aggregator checks. | CE10, CE11, CE14 |
| M23 | Commitment Chain | The privacy claim concerns the expanded aggregation view, not a wire-vector size. | Clarify representation and explain why aggregate frame size is not reported without a complete serialization benchmark. | CE14, CE26 |
| M24 | Commitment Chain | Each submitted report has an explicit frame and public statement. | Define report syntax, witness, and per-role validation. | CE03, CE10, CE11 |
| M25 | Commitment Chain | The identity commitment binds the enrollment secret and user identifier. | Define identity binding and off-chain authentication. | CE10 |
| M26 | Commitment Chain | The Shuffler checks continuity against the previously accepted current hash. | State client state-storage implications. | CE10 |
| M27 | Distance Circuit | The distance circuit makes SHTPC predicates one accepted statement. | State circuit motivation and advantage. | CE02, CE03, CE11 |
| M28 | Distance Circuit | The main circuit uses a compile-time window constant. | Define the evaluated window parameterization. | CE03, CE04 |
| M29 | Distance Circuit | A signed timing token binds the step duration to user, epoch, and round. | Specify server-issued motion budgets. | CE09, CE10 |
| M30 | Distance Circuit | The public statement and private witness have explicit fields. | Separate visible binders from hidden coordinates and openings. | CE03, CE14 |
| M31 | Distance Circuit | Six constraint groups implement trajectory, identity, mode, and payload checks. | Map C1-C21 to their predicates. | CE03, CE11 |
| M32 | Distance Circuit | The evaluated relation compiles to generated circuit facts. | Bind Method numbers to the evaluated R1CS evidence. | CE04 |
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
| M45 | Circuit Details | The evaluated arity-3 Poseidon circuit has the generated constraint count. | Repeat the evaluated artifact fact at implementation detail. | CE04 |
| M46 | Integer Semantics | Every ordered BN254 value is range-checked before comparison. | Exclude field-wraparound ambiguity. | CE12 |
| M47 | Binding Tests | The implementation mutates every modeled binder and route field after a valid baseline. | Summarize deterministic negative-test coverage. | CE05, CE11 |

### Evaluation

Section thesis: each RQ tests a stated admission boundary or residual risk,
while original-input utility, protocol smoke, and validated scale execution
remain non-interchangeable evidence layers.

| Paragraph | Manuscript location | Topic sentence | Role | Claim IDs |
|---|---|---|---|---|
| E01 | Evaluation opening | The evaluation follows the narrowed paper claims. | Map RQ1-RQ6 and exclude general truthfulness/robustness. | CE08, CE16, CE17, CE18, CE19, CE23 |
| E02 | Experimental Setup | The data-and-protocol paragraph defines five inputs, experiment scales, defaults, and metrics. | Give the common configuration without duplicating per-RQ protocols. | CE01, CE07, CE16, CE17, CE19 |
| E03 | Experimental Setup | The comparisons-and-execution paragraph names measured baselines and the Docker scale protocol. | Establish fairness, hardware allocation, RQ5 seeds, and the 7,200-second timing rule while leaving adapter details to RQ5. | CE07, CE23, CE26 |
| E08 | RQ1 | RQ1 asks whether SHTPC rejects proof/payload-inconsistent reports. | State target attack and ablation purpose. | CE11, CE16 |
| E09 | RQ1 | SHTPC-Full rejects all modeled A1, A2a, A3, A5, and A6 violations. | Report scoped ablation result and mechanism attribution. | CE16 |
| E10 | RQ1 | A6 is also tested by 12 deterministic payload-binding mutation attempts. | Report the two proof/public-signal, five private-witness, and five post-proof route attempts and connect them to the static gate. | CE05, CE11 |
| E11 | RQ2 | RQ2 asks how statefulness affects predecessor, replay, and window consistency. | Compare context-only state to in-relation primary equality. | CE17 |
| E12 | RQ2 | Boundary sweeps separate per-step and window continuity predicates. | Explain transition locations without changing policy semantics. | CE17 |
| E13 | RQ2 | A3 is evaluated as a parameterized ADWC admission check. | Report K6/K30 sensitivity and deployment recommendation. | CE17 |
| E14 | RQ2 | The tau/tau2 sweep checks DP-parameter invariance and session withholding. | Separate admission verification from DP settings. | CE17, CE20 |
| E15 | RQ3 | RQ3 asks what remains inferable from Shuffler-visible leakage. | Report the classifier, synthetic sample split, real user-disjoint split, exact four-dataset session AUC, and leakage boundary. | CE18 |
| E16 | RQ4 | RQ4 asks what remains after the cryptographic envelope is enforced. | State bounded influence but not ground-truth defense. | CE08, CE19 |
| E17 | RQ4 proposition | Accepted malicious mass and support are bounded by clipping and reachability. | Provide an analytical influence bound. | CE19 |
| E18 | RQ4 joint adversary | SHTPC enforces an envelope, not ground truth. | Report payload-decoupled rejection and in-envelope acceptance. | CE19 |
| E18a | RQ4 hotspot sweep | A complementary GeoLife sweep varies the malicious fraction from 1% to 30%. | Show when false Top-20 hotspots emerge and why envelope and external controls are complementary. | CE19 |
| E19 | RQ5 | RQ5 fixes one five-dataset utility protocol without per-dataset retuning. | Define N=1000, ten rounds, three seeds, epsilon 5, tau 2, 10% A1, and top-50 Jaccard. | CE07 |
| E20 | RQ5 | SHTPC has five positive mean Jaccard deltas over the external ESA adapter and exceeds the EIFFeL-style adapter on all five inputs. | Report every ESA absolute value, all 15 observed positive paired differences, and the EIFFeL-style means while withholding statistical-significance claims for the three-seed small gains. | CE07, CE20 |
| E21 | RQ6 functional result | The evaluated Groth16 relation completes the validated 15-unit matrix. | Report generated circuit facts, passing checks, proof/route totals, reconstruction, and DP-release completion from generated evidence. | CE04, CE05, CE06, CE23 |
| E22 | RQ6 timing result | The scale table separates functional completion from timing eligibility. | Report 13-unit timing statistics, disclose Rome/101 and Synthetic/101 host suspension, and reject an interactive-latency interpretation. | CE23 |

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
| C01 | Conclusion | This paper formulates SHTPC as a narrow admission-consistency goal. | Restate insight, evaluated circuit identity, verified scale execution, and deployment boundary. | CE03, CE04, CE08, CE16, CE18, CE19, CE23, CE27 |
| C02 | Future Work | Future work should strengthen enrollment, Shuffler auditability, adaptive evaluation, and setup portability. | Route excluded risks and throughput optimization to future work without claiming they are solved. | CE08, CE23, CE24 |

## Review Gate

- Abstract contains all five scoped messages and includes only the verified
  functional scale totals, not an interactive-latency claim.
- Every retained major claim has a non-`unsupported` status and an action.
- CE01 and CE26 are closed by the Task 7 citation and artifact audits; CE25 is
  an explicit assumption rather than an unsupported governance analogy.
- Retired circuit-lineage and benchmark-lineage records support no reviewer-facing claim.
- The fixed fair five-dataset evidence is integrated in E02, E02a, and E19-E20.
- CE23 is bound to strict aggregate SHA-256
  `2ad8e35340d0646c3b0e130468f9a00c5b66e433bedf4411929fe9f166516a95`.

## Five-Dimension Adversarial Self-Review

Statuses in this checklist are `pass`, `needs revision`, or
`needs new experiment`. A `needs revision` item remains a mandatory downstream
task and is not treated as paper-ready.

| Dimension | Reviewer question | Status | Evidence or required action |
|---|---|---|---|
| Contribution | What new knowledge does the paper provide? | pass | CE02-CE03 isolate same-relation trajectory/payload binding as the contribution. |
| Contribution | Is the failure case meaningful rather than trivial? | pass | I02-I03 show a valid hidden proof can be paired with a different routed primary without the new relation. |
| Contribution | Is the idea non-obvious beyond standard composition? | pass | The composition-gap proposition and CE11 explain why state/context or VDAF-style checks alone do not imply equality. |
| Contribution | Is the empirical gain stated without exaggeration? | pass | Abstract and RQ5 say two of five positive Jaccard deltas are small; CE07 retains every exact mean and RQ5 makes no statistical-significance claim for the three-seed small differences. |
| Contribution | Is at least one novelty type explicit? | pass | The paper claims a new scoped admission property and one-relation system design, not a new proof system or DP mechanism. |
| Writing clarity | Can a knowledgeable reader reproduce the method? | pass | Method details are paired with the Heatmap artifact index, exact commands, pass criteria, and evidence-layer boundaries. |
| Writing clarity | Are key modules technically specified? | pass | M17-M47 cover state, binders, transport, circuit, timing, warmup, DP, and integer semantics. |
| Writing clarity | Is each module motivated by a concrete challenge? | pass | M17, M27, and M36 explicitly connect design choices to the proof/payload gap and enrollment boundary. |
| Writing clarity | Are terms and notation consistent? | pass | SHTPC terminology, generated circuit facts, and `eq:r-shtpc` are consistent; reviewer-visible internal version labels and drafting notes are absent. |
| Writing clarity | Does every core-section paragraph carry one message? | pass | The reverse outline records one topic sentence and role per prose paragraph/list contribution, including separate scale functional and timing messages. |
| Experimental strength | Are improvements over the strongest fair baseline meaningful? | pass | RQ5 reports all five deltas and distinguishes GeoLife/T-Drive/Rome gains from the small Porto/Synthetic gains. |
| Experimental strength | Is absolute performance competitive? | pass | Figure 5 and its result paragraph expose mean Jaccard, standard-deviation ranges, every ESA delta, EIFFeL-style means, FRR, and MRR under one fixed protocol. |
| Experimental strength | Are gains consistent across datasets and seeds? | pass | CE07 binds five positive mean deltas, 15 positive observed dataset-seed differences, and three-seed standard deviations under one fixed configuration without converting that observation into a significance claim. |
| Experimental strength | Are strengths and failure cases reported honestly? | pass | CE08, CE18, and CE19 keep metadata and in-envelope failures visible in Abstract and Discussion. |
| Evaluation completeness | Are key design choices ablated? | pass | CE16-CE17 cover ADWC, payload binding, context-only state, and no-admission variants. |
| Evaluation completeness | Are strong baselines compared fairly? | pass | The headline uses one fixed protocol. The external ESA adapter is the strongest evaluated comparison on all five inputs. Its sampling, raw-count threshold 3, and debiasing rules are explicit. Tuned results stay out of the table, and the text does not present the adapter as a native upstream deployment. |
| Evaluation completeness | Are metrics sufficient and separated by evidence layer? | pass | E04-E07, CE20, and CE23 separate rejection, utility, protocol smoke, and evaluated scale execution. |
| Evaluation completeness | Are datasets sufficiently broad? | pass | The manuscript integrates four real trajectory-derived inputs and one explicitly generated clustered random-walk stress input. |
| Evaluation completeness | Is the protocol documented clearly? | pass | Experimental Setup separates original-input utility, safe-trajectory protocol smoke, and full Groth16 scale in three paragraphs. |
| Method soundness | Is the deployment setting realistic? | pass | CE09, CE25, and CE27 restrict the claim to managed deployments and state that administrative separation is assumed rather than inferred from regulation. |
| Method soundness | Are hidden technical defects addressed? | pass | CE05 and CE11 bind the evaluated circuit to 22 compatibility/tamper checks and negative fixtures. |
| Method soundness | Does the fair result avoid per-dataset retuning? | pass | CE07 uses one epsilon/tau pair across all datasets; tuned results are not the headline comparison. |
| Method soundness | Are complexity and limitations visible? | pass | Discussion and CE08/CE14/CE18/CE24 expose leakage, collusion, setup, enrollment, and in-envelope limits. |
| Method soundness | Is the net benefit supported at paper scale? | pass | CE23 verifies every functional unit and reports all timing-eligible units; the manuscript also states that the measured 4.183-hour mean unit runtime is reproducible execution evidence, not interactive performance. |

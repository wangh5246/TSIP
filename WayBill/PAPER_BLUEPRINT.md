# WayBill paper blueprint

## Paper configuration

| Field | Decision |
|---|---|
| Mode | Academic-paper revision |
| Paper type | Methods and security systems paper |
| Field | Privacy-preserving intelligent transportation and applied cryptography |
| Target style | Generic IEEE-style blind review with Nature-leaning argument structure |
| Main language | English drafted from Chinese author context |
| Citation style | IEEE numeric |
| Output | LaTeX and PDF |
| Evidence baseline | Canonical differential receipt plus repaired pre-release worktree; successor M4 release pending |

## One-sentence argument

In GNSS-based road-usage charging, WayBill separates profile-defined origin-label admissibility from zero-knowledge tariff computation and combines it with odometer-backed month close, which prevents outage manipulation or period withholding from creating a discount relative to acquisition-supplied, receiver-sealed tariff labels under explicit sensing and odometry assumptions.

## Reader path

1. Relevance. Disclosure-minimizing road-usage charging should avoid raw trajectories without losing settlement completeness.
2. Novelty. The receiver, rather than the prover, owns interval validity, and month-level odometry accounts for periods that never reach the verifier.
3. Trust. The paper provides an exact relation, a scoped theorem, an end-to-end receipt, and a preregistered formal evaluation.
4. Reuse. Version-pinned code, containers, manifests, and receipts define a reproducible execution boundary.
5. Meaning. The guarantee is conditional on receiver and odometer integrity and does not imply physical-location truth or route indistinguishability.

## Terminology ledger

| Canonical term | First-use definition | Variants to avoid |
|---|---|---|
| road-usage charging (RUC) | Zone or distance-based charging from vehicle use | road pricing when the protocol-specific meaning is intended |
| WayBill | The complete settlement system | V6 system, framework, scheme |
| receiver signer | Process-isolated signer that derives profile admissibility and seals acquisition records | independent hardware, sensor oracle, trusted biller |
| charger | Verifier and ledger service that accepts periods and closes months | charging authority when referring to the protocol role |
| origin-label admissibility bit | Profile-derived bit $v_i$ for the outgoing interval of fix $i$ | physical position validity, fallback flag under prover control |
| validity-bound receiver root | $R_{\mathrm{fix}}$ committing fixes and validity bits | fix root when validity binding matters |
| policy profile | Versioned binding of circuit, tariff, maximum rate, and verification key | configuration, policy file |
| period statement | Public 22-field settlement statement verified with the proof | proof request, bill tuple |
| month-close reconciliation | Maximum-rate charge for attested distance not covered by accepted periods | monthly fallback |
| sealed-label reference bill | $Q_{\mathrm{auth}}$ defined over acquisition-supplied, receiver-sealed tariff labels | ground-truth bill |
| canonical differential receipt | Checked-in 25-fix end-to-end V6 evidence | full experiment result |
| formal evaluation | Preregistered four-dataset S1--S5 server run | M4, broader run |

## Section architecture

1. Abstract. Problem, gap, WayBill mechanism, theorem, canonical receipt, and boundary.
2. Introduction. RUC privacy-completeness tension, prior approaches, unresolved omission problem, and three contributions.
3. Related Work. Private tolling and completeness, then trusted location and metadata leakage.
4. System and Threat Model. Parties, trust base, adversary, security goals, and declared privacy view.
5. WayBill Design. Receiver-sealed validity, period relation, month close, and verifier state transition.
6. Security Analysis. Conditional no-discount theorem, replay binding, and limits of the theorem.
7. Implementation. Receiver signer, charger, circuit, pinned artifacts, and receipt discipline.
8. Evaluation. Canonical evidence, RQ1--RQ5, datasets, baselines, metrics, ablations, and strict result boundary.
9. Discussion. Interpretation, relation to prior work, sensing and metadata risks, recourse, availability, and deployment boundary.
10. Conclusion. Contribution, decisive evidence, implication, and bounded future work.

## Claim-evidence map

| Claim | Evidence | Status |
|---|---|---|
| The prover cannot self-declare an outage | Validity is derived by the receiver signer and committed in $R_{\mathrm{fix}}$ | Supported by implementation and tests |
| Withholding cannot create a discount relative to sealed labels after successful close | Conditional economic-conservatism theorem and month-close equation | Supported under stated assumptions |
| Replay and public-signal tampering fail | Canonical endpoint receipt and focused tests | Supported |
| The canonical proof path is executable | 25-fix receipt with constraints, proving, verification, and exact vector agreement | Supported as a single artifact run |
| Circuit and CLI/in-process workloads scale over the frozen matrices | S2 and S5 scientific aggregate | Needs server evidence; no PostgreSQL inference |
| Formula-level mechanism sensitivity remains conservative under trace-derived outages, odometer error, and withholding | S1 scientific aggregate | Needs server evidence; not end-to-end implementation validation |
| Bounded cell/trajectory displacement and tariff granularity have measured effects | S3 strict aggregate | Needs server evidence; not signal-level relay validation |
| Bucketed views reduce linkage risk | S4 strict aggregate | Needs server evidence |

## Assumptions or missing inputs

- Target venue and final page limit are not yet fixed. The current manuscript remains IEEE-style and blind-review safe.
- S1--S5 quantitative claims, target-host specifications, confidence intervals, and final figures must come from strict merge.
- Author names, CRediT roles, funding, conflicts of interest, institutional ethics determination, and AI-use wording require author confirmation.
- The direct Groth16 setup remains test-only and cannot support a production-ceremony claim.
- `waybill-formal-readiness-v2` is superseded for M4; a new verified release and target RG6 are mandatory before launch.

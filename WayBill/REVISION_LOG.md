# WayBill manuscript revision log

This log records the first evidence-bounded revision pass. It does not treat a planned experiment as a completed result.

| Issue found | Revision | Status |
|---|---|---|
| The novelty claim was distributed across implementation details | Reframed the paper around receiver-sealed validity, proof-scoped correctness, and odometer-backed completeness | Resolved |
| The abstract mixed completed measurements with planned metadata evaluation | Rewrote it as context, gap, method, conditional guarantee, canonical evidence, and explicit pending evaluation | Resolved |
| Related work appeared after the evaluation and lacked a current synthesis | Moved it after the introduction and added a verified 2023 survey and 2024 deployment case study | Resolved |
| The method began with protocol internals rather than an input-output view | Added a design overview and organized the method by four settlement mechanisms | Resolved |
| Internal V5/V6 version language obscured the transferable idea | Retained versions only where they identify concrete schemas or receipts | Resolved |
| Evaluation tense could imply that S1--S5 had run | Marked the protocol as pre-registered, changed planned analyses to future tense, and added result insertion slots | Resolved |
| The canonical receipt risked being read as a complete experiment | Added a dedicated evidence-boundary subsection and retained every S1--S5 stage as pending | Resolved |
| Privacy could be overread as route anonymity | Declared the charger-visible tuple and limited the claim to disclosure minimization and empirical linkage analysis | Resolved |
| Physical location truth could be overread from OSNMA | Stated that navigation-message authentication does not prove receiver presence or defeat all relay attacks | Resolved |
| Submission declarations were absent | Added a nonblind declarations file with explicit author-input placeholders | Partially resolved |
| Full four-dataset evidence is unavailable | No result was invented; this remains the principal empirical limitation until the strict server aggregate passes | Deliberate limitation |
| Production proof-system governance is incomplete | Retained the test-only setup warning and production-ceremony requirement | Deliberate limitation |
| Receiver wording implied physical verification | Replaced it with acquisition-supplied, receiver-sealed origin-label admissibility and made acquisition logic part of the TCB | Resolved |
| The theorem sounded like a new completeness primitive | Renamed it successful-close conditional economic conservatism and explained the maximum-rate-deposit/verified-discount abstraction | Resolved |
| Endpoint and S5 wording implied production load | Limited the evidence to TestClient/SQLite endpoint logic and in-process handler functional concurrency | Resolved |
| S1 could be read as end-to-end V6 validation | Limited it to formula-level trace mechanism sensitivity | Resolved |
| Error recourse and institutional independence were underspecified | Added a dispute-state-machine requirement, provisional-charge/fairness limitations, and governance roles | Resolved as design requirements; not implemented |
| Old V2 runner semantics are not launchable | Marked V2 superseded/no-go and required a new commit/tag/image/SIF/release/RG6 chain | Open launch blocker |

## Inputs still required before submission

- Confirm the target venue, page limit, and anonymity policy.
- Run and strictly merge S1--S5 on the server.
- Replace declaration placeholders for ethics, author roles, funding, conflicts, and AI-assisted writing.
- Replace the test-only Groth16 setup for any production claim.
- Freeze and verify a successor formal release; never execute M4 from V2.

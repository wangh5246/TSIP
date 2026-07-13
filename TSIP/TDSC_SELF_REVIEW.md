# TDSC Self-Review

Status: in progress. The full five-dimension adversarial review, fresh build
receipt, rendered-page inspection, and final claim-evidence closure are Task 9
outputs. This checkpoint records the submission gate that must not be lost
during compilation.

## Blocking Author Gate

**BLOCKED: explicit author license selection required**

The repository has no approved top-level license. A `LICENSE` file must remain
absent until the authors select an SPDX license and confirm that all copyright
holders authorize it. Dataset and dependency licenses do not answer this gate.

## Evidence Boundary

- Fixed utility is verified for five datasets, three seeds, N=1000, and ten
  windows at epsilon 5 and tau 2.
- The Docker launcher records 15/15 execution pass, but scale latency and
  throughput remain unverified until a strict aggregate validates all 15 unit
  receipts and their manifest/launch bindings.
- Simulated reviewer reports are internal quality control only.
- The checked-in Groth16 setup is a development reproducibility artifact, not a
  production ceremony.

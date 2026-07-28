# WayBill P1 Charger Hardening Implementation Plan

Date: 2026-07-28

Design: `docs/superpowers/specs/2026-07-28-waybill-p1-charger-hardening-design.md`

## Phase 1 — protocol-domain binding

1. Add `charger_domain` to receiver sealed-log state and the versioned root
   attestation payload.
2. Add a versioned, Charger-domain-bound monthly odometer attestation.
3. Update receiver configuration, fixture loading, proof generation, schemas,
   and protocol tests.
4. Add negative tests for cross-domain replay.

## Phase 2 — transactional storage

1. Add pinned SQLAlchemy and PostgreSQL driver dependencies.
2. Implement the Charger settings model, relational schema, bootstrap checks,
   and transactional repository.
3. Move device registry, period acceptance, month attestation, reconciliation,
   month close, status, and reset behind the repository.
4. Preserve exact external settlement arithmetic and response fields while
   removing all mutable module-level dictionaries.

## Phase 3 — authenticated application boundary

1. Refactor the Charger into `create_app(settings)` with lifespan-managed
   storage.
2. Enforce the endpoint authorization matrix and fail-closed configuration.
3. Disable transparent endpoints by default and restrict reset to explicit
   test mode.
4. Update scripts, tests, Docker assets, environment examples, and server
   runbook.

## Phase 4 — verification and evidence

1. Run focused protocol, Charger, month-close, and policy tests.
2. Run restart, transaction rollback, concurrency, and authorization tests on
   SQLite.
3. Run the same integration contract against PostgreSQL when a local container
   runtime is available; otherwise mark that gate pending without weakening it.
4. Run the full test suite, flake8, mypy, configuration validators, artifact
   checks, and paper/knowledge-base lint.
5. Update the engineering review, P1 result report, experiment ledger, project
   plan, and Obsidian memory with exact receipts and remaining limitations.

# WayBill P1 Charger Hardening Design

Date: 2026-07-28

Baseline: P0 implementation on `codex/waybill-formal-readiness-v2`

Decision owner: the project owner authorized the recommended design and stated
that the formal experiments may run on a rented server without tight resource
constraints.

## 1. Goal and scope

Replace the Charger service's process-local dictionaries and unauthenticated
mutation endpoints with a restart-safe, transactionally serialized service.
Bind canonical proof-only settlement artifacts to one configured Charger
domain so a proof package accepted by one operator cannot be replayed at a
different operator.

This phase establishes a production-shaped persistence and authentication
boundary. It does not claim Byzantine replication, automatic failover, HSM key
custody, DDoS resistance, or multi-region availability. Those claims require a
separate deployment and fault-injection campaign.

## 2. Considered approaches

### A. Locks around the current dictionaries

This is the smallest patch, but state still disappears on restart and a crash
between ledger updates can leave partial state. It cannot support the paper's
month-close durability argument.

### B. SQLite-only persistent service

SQLite WAL plus `BEGIN IMMEDIATE` provides a sound single-process artifact
backend and inexpensive tests. It does not provide an honest multi-worker or
multi-host server path.

### C. One relational model with PostgreSQL production and SQLite tests — selected

Use SQLAlchemy Core to define one normalized schema and transaction API.
PostgreSQL is the server backend and uses row locks to serialize per-device and
per-month mutations. SQLite WAL is the local/CI backend and uses an immediate
write transaction. This keeps local verification deterministic while allowing
the rented-server experiment to exercise the production database path.

## 3. Trust and deployment boundaries

Each Charger deployment has a non-empty stable `charger_domain`, for example
`ruc-demo.charger-01`. The value identifies a settlement operator boundary,
not merely a DNS name, and must not change while signed artifacts remain live.

The independent receiver signer is configured with the intended
`charger_domain`. It stores that domain in every sealed log and signs it in the
root attestation. The canonical proof-only Charger endpoint accepts an
attestation only when its signed domain exactly equals the local configured
domain. The prover cannot choose or rewrite this value.

Monthly odometer attestations move to a versioned payload that also signs the
same domain. This closes the corresponding cross-Charger replay path at month
close.

Transparent raw-fix endpoints remain evaluation-only and are disabled unless
an explicit setting enables them. The production deployment exposes the V6
proof-only endpoint; therefore its replay boundary consists of the signed
Charger domain, a domain-local device credential, and the database uniqueness
constraint on `(device_id, period_id)`.

## 4. Authentication and authorization

Bearer tokens are opaque, randomly generated credentials. The database never
stores a plaintext device token. It stores an HMAC-SHA-256 digest under a
server-side token pepper and compares digests in constant time.

| Endpoint class | Required principal |
| --- | --- |
| `/health` | none; returns aggregate readiness only |
| device registration | administrator |
| proof/period submission | matching device |
| monthly odometer attestation | matching device |
| month status/reconciliation | administrator |
| month close | administrator |
| reset | administrator plus explicit test-only enable flag |

Registration is create-once. Re-registering the same device is idempotent only
when the public key, jurisdiction, and credential digest are identical;
otherwise it fails with conflict. Key rotation is deliberately not overloaded
onto registration and will require an auditable rotation endpoint.

Missing configuration fails closed at application startup. The server requires
a database URL, Charger domain, administrator token, and token pepper.

## 5. Relational state model

The initial schema version contains:

- `charger_meta`: schema version and configured Charger-domain fingerprint;
- `devices`: device ID, public key, jurisdiction, credential digest, timestamps;
- `periods`: immutable accepted public statement, normalized month, interval,
  fee, distance, fallback count, reconciliation rate, and acceptance time;
- `month_attestations`: one signed, domain-bound odometer statement per
  device-month;
- `month_states`: aggregate counters, canonical reconciliation rate, lifecycle
  (`open`, `closed`, or `administrative-exception`), and immutable receipt;
- `audit_events`: append-only security-relevant mutations without plaintext
  credentials or private proof witness material.

The service derives month aggregates from committed database rows and updates
the cached counters in the same transaction. Database constraints enforce
non-negative arithmetic, canonical month identity, unique period IDs per
device, and one month state/attestation per device. Public statements and
receipts are stored as canonical JSON plus SHA-256 for corruption detection.

## 6. Transaction and concurrency semantics

Period acceptance performs proof/signature/policy verification before opening
the write transaction. Inside one transaction it:

1. locks the device row and target month row (PostgreSQL) or obtains the SQLite
   immediate writer lock;
2. rechecks the device enrollment, credential, month lifecycle, replay key,
   and interval overlap;
3. inserts the immutable period;
4. updates the month counters and maximum canonical reconciliation rate;
5. appends an audit event;
6. commits once.

Concurrent duplicate or overlapping periods therefore have at most one
winner. A process crash before commit leaves no visible acceptance; a crash
after commit is recovered from the database without reconstructing state from
memory.

Attestation insertion, administrative exception creation, and month close use
the same per-device/per-month serialization. An identical attestation or close
request returns the original result idempotently. A conflicting request fails.
Closed or administrative months never return to `open`.

## 7. Error handling and observability

Expected domain errors map to stable HTTP statuses: 401 for absent/invalid
credentials, 403 for a valid credential used for another device, 409 for
replay/conflict/closed-month state, and 503 for unavailable persistence.
Unexpected database errors roll back the transaction and never return a
successful acceptance receipt.

Health reports the backend kind, schema version, Charger domain, database
connectivity, and aggregate row counts. It exposes no device identifiers,
tokens, statements, or billing records.

Audit events record registration, period acceptance, month attestation, month
close, administrative exception, and test reset. Token material and raw fixes
are never written to the audit log.

## 8. Compatibility and migration

There is no implicit import of module-level dictionary state because that state
was non-durable and cannot be trusted after a restart. A deployment starts from
an empty schema, registers devices through the authenticated operator path, and
then begins acceptance.

Receiver root attestation and monthly odometer attestation schemas are bumped.
Legacy unbound attestations are rejected by the production Charger. Fixture and
proof-generation scripts are updated together so canonical V6 artifacts all
carry the same domain.

SQLite remains a supported evaluation backend, not the formal server backend.
The server guide uses PostgreSQL, one Charger application instance initially,
explicit secrets, a persistent volume, and a readiness check. Multi-worker
claims are gated on the concurrency tests passing against PostgreSQL.

## 9. Verification gates

The P1 gate requires automated evidence for:

- invalid/missing administrator and device credentials;
- cross-device credential use;
- cross-Charger root and monthly-attestation replay;
- duplicate and overlapping concurrent period submissions;
- conflicting concurrent month attestations and month closes;
- process restart preserving enrollment, replay state, ledgers, attestations,
  closed months, and immutable receipts;
- injected failure before commit leaving no partial ledger update;
- SQLite local suite and PostgreSQL integration suite producing equivalent
  settlement outcomes;
- dependency, lint, type, configuration, artifact, and full regression checks.

The paper and Obsidian memory may state only the gates actually exercised. A
PostgreSQL code path without a PostgreSQL receipt is described as implemented
but not experimentally validated.

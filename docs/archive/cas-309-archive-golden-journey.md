# CAS-309: Golden local Archive journey

This document turns the [minimal local Archive contract](cas-309-local-archive-contract.md)
into executable examples. The examples are intentionally few: one real Policy
vertical slice proves the foundation, and later domain slices extend the same
shape without expanding Archive into a platform.

## Golden 1: write, exit, and reopen Policy

The first production example writes a complete non-default `Policy`, drops the
Archive handle, reopens the same root, and reads an equal Policy using only its
serialized `PolicyArchiveRef`.

Required observations:

- the caller supplies no format, schema, or writer version;
- the typed result of `write(&policy)` is `PolicyArchiveRef`;
- the typed result of `read(&policy_ref)` is `Policy`;
- the record key is an Archive-assigned UUID, so authored Policies that happen
  to resolve to equal effective behavior still round-trip as their own values;
- deserialization runs Policy's existing invariant validation;
- no explicit `close` or flush method exists;
- a fresh process produces the same result as a same-process reopen.

## Golden 2: automatic writer provenance

The committed JSON record contains the exact `yosoi-archive` package version
from Cargo. A test compares that field to `env!("CARGO_PKG_VERSION")` rather
than duplicating a release string in source or fixtures.

Changing only the package release does not change archive format 1 or Policy
record schema 1. Reading and retrying publication of the same assigned record
key preserves the already committed record.

## Golden 3: reject a future schema before value decoding

Start with a valid Policy record, change `schema_version` to `2`, and replace
`value` with JSON that cannot deserialize as Policy.

The read must return `MigrationRequired` with record kind, found schema,
supported schema, and original writer provenance. It must not return a Policy
Serde error, proving header validation happened first.

## Golden 4: typed kind and key integrity

- A Policy record copied under another valid Policy key returns a key mismatch.
- A structurally valid record whose header says another kind returns a kind
  mismatch before value decoding.
- Application code cannot pass `PolicyArchiveRef` where a future
  `CaptureArchiveRef` is required.
- Parsing a textual ref validates structure but does not claim the record
  exists.

## Golden 5: immutable retry and conflict

- Two ordinary writes of the same Policy create two immutable snapshots with
  different Archive-assigned references.
- Concurrent publication attempts for one already assigned key and equal value
  publish one logical record and both resolve to the same reference.
- A pre-existing different value under the same logical identity returns
  `IdentityConflict` and remains byte-for-byte unchanged.
- A reader never observes a staged or partially written record.

Concurrency tests use explicit barriers or channels around publication. They do
not use sleeps as readiness or synchronization.

## Golden 6: first readable tree

After one successful Policy write, the meaningful tree is:

```text
.yosoi/archive/v1/
├── records/policy/<shard>/<policy-key>.json
└── staging/
```

The JSON is human-inspectable and contains automatic writer provenance, record
kind, Policy schema version, logical key, and the complete validated Policy.
There is no database, index, lock daemon, global configuration, or hidden user
directory.

## Downstream golden: archive now, evaluate later

The integrated example begins with one request capture containing exact source
and decoded evidence. It archives the CaptureBundle, validated authored Policy,
compiled Plan, serializable ContractSchema, and exact normalized Documents, then
ends the writer process before any locator or Contract evaluation.

The reader process has no request target, client, provider handle, or browser.
It reopens the typed EvaluationRun and exact Document representations, and runs
the existing locate, extract, and validate calls. Raw browser artifacts remain
provenance and normalization inputs; they are never relabeled as Documents. The immediate and
offline outcomes must agree in terminal state, order, values, coordinates,
region lineage, completeness, diagnostics, issues, provenance, and identities.

The caller can then archive the result explicitly. LocatorRunRecord stores the
exact LocateOutcome (for example `author → John Doe`), while ContractRunRecord
stores a schema-checked archived representation of validated records, issues, and
diagnostics that remains readable without compiled Contract code. Neither read
operation reruns evaluation.

Source HTML, decoded text, rendered DOM, accessibility tree, JSON, and XML
remain distinct inputs. No golden substitutes one representation for another,
and examples contain no hard-coded CSS, XPath, attribute, or browser selectors.

## Focused validation order

1. Compile the public Policy example.
2. Run Policy record/ref/wire unit tests.
3. Run temporary-directory same-process and fresh-process tests.
4. Run immutable retry, concurrent write, and publication-boundary tests.
5. Run focused formatting, check, and Clippy for `yosoi-archive` and `yosoi`.
6. Run the broader workspace suite serially only after focused checks pass.

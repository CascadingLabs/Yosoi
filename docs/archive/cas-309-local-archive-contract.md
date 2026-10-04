# CAS-309: Minimal local Archive contract

Status: approved contract for the first local implementation

Linear: [CAS-309](https://linear.app/cascadinglabs/issue/CAS-309/approve-the-minimal-local-archive-contract)

Companion: [golden Archive journey](cas-309-archive-golden-journey.md)

## Plain English

Yosoi Archive saves exact request evidence and the definitions needed to use it
again. A later process can reopen local `.yosoi` files, reconstruct the same
Documents, and run locating or Contract evaluation without making another
request or starting a browser.

The first Archive is a local serialization tool. It is not a database, query
engine, replay service, storage-provider framework, or data lake.

## First user story

An online process completes a request attempt and receives one validated
`CaptureBundle`. The caller has a validated authored `Policy`, a compiled `Plan`, and
optionally a serializable `ContractSchema`, but chooses not to evaluate them yet.

The online process writes those values, every exact normalized `Document`, and
one small run record, then exits. `RequestRunRecord` preserves request and
projection provenance; `EvaluationRunRecord` packages the Capture, Policy,
Plan, optional ContractSchema, and ordered Documents needed for offline work.

A later offline process opens the same Archive and typed references. It reads
the exact evaluator-ready Documents, then calls the existing synchronous locate,
extract, and validate APIs. The caller may explicitly archive the resulting
`LocateOutcome` and Contract result as new immutable records. Archive
performs no implicit evaluation during `read`.

## Public SDK

The stable shape is one concrete asynchronous local handle with strictly typed
single-value operations:

```rust,no_run
use std::error::Error;
use yosoi::prelude as ys;

async fn archive_policy() -> Result<(), Box<dyn Error>> {
    let archive = ys::Archive::open(".yosoi").await?;
    let policy = ys::Policy::default();

    let policy_ref: ys::PolicyArchiveRef = archive.write(&policy).await?;
    let serialized_ref = policy_ref.to_string();

    // Optional. Scope exit is sufficient because Archive owns no background
    // writer and every operation awaits its own file handles.
    drop(archive);

    let archive = ys::Archive::open(".yosoi").await?;
    let policy_ref: ys::PolicyArchiveRef = serialized_ref.parse()?;
    let reopened: ys::Policy = archive.read(&policy_ref).await?;
    assert_eq!(reopened, policy);
    Ok(())
}
```

Rust does not provide ordinary method overloading. Archive preserves the desired
surface through sealed, type-directed dispatch: the input value selects the
exact reference returned by `write`, and the reference selects the exact value
returned by `read`. Applications cannot opt arbitrary types into persistence.

The first implementation has no batch write, tuple read, erased value enum, or
pluggable Archive codec/provider trait. Those conveniences require concrete
resource and failure semantics before they join the SDK.

Contract results use the same surface. The Contract derive implements
`ArchivedContract`, so callers never invoke a codec or construct an intermediate
serialization value:

```rust,ignore
let outcome = Author::extract(&located).validate();
let run = ys::ContractRunRecord::new(locator_ref, schema_ref, &outcome)?;
let run_ref = archive.write(&run).await?;

let reopened: ys::ContractRunRecord = archive.read(&run_ref).await?;
let authors: Vec<Author> = reopened.values()?;
```

`ContractRunRecord` stores its schema snapshot beside the outcome and retains
the typed schema reference as provenance. Archive checks that both schemas are
identical on write and read. Code-independent tools may inspect
`ys::archived::*`; ordinary typed callers do not need that namespace.

## Local-project values

| Value | Typed reference | Durable ownership |
| --- | --- | --- |
| `CaptureBundle` | `CaptureArchiveRef` | `WebCaptureWire` plus manifest-required retained payload bytes |
| `Policy` | `PolicyArchiveRef` | Complete validated authored policy |
| `Plan` | `PlanArchiveRef` | Complete validated compiled locator plan |
| `ContractSchema` | `ContractSchemaArchiveRef` | Serializable Contract definition, never generated Rust code |
| `Document` | `DocumentArchiveRef` | Exact validated evaluator-ready bytes, ID, and profile |
| `RequestRunRecord` | `RequestRunArchiveRef` | Ordered request attempts, Capture refs, and projection outcomes |
| `EvaluationRunRecord` | `EvaluationRunArchiveRef` | Links Capture, definitions, and ordered archived Documents |
| `LocatorRunRecord` | `LocatorRunArchiveRef` | Exact typed LocateOutcome plus EvaluationRun and Document provenance |
| `ContractRunRecord` | `ContractRunArchiveRef` | Code-free validated Contract values, issues, diagnostics, and terminal state |

Domain types keep their invariants. Plain durable structs derive Serde;
invariant-bearing types deserialize through their existing validated
constructors. `CaptureBundle` remains intentionally non-Serde and reconstructs
through `CaptureBundle::builder`.

The adapters all use the same closed `Archive::open`, `write`, and `read`
surface. Adding a new durable kind requires an Archive-owned adapter and typed
reference; application crates cannot register arbitrary codecs.

## Record keys and same-key equality

Hashes are not the default Archive identity. The first project makes these
choices explicitly:

| Kind | Record key | Same-key equality |
| --- | --- | --- |
| Capture | Existing `CaptureId` occurrence identity | Complete `WebCaptureWire` plus every manifest-required retained payload byte |
| Policy | Archive-assigned UUID | Complete validated authored `Policy` |
| Plan | Archive-assigned UUID | Complete validated `Plan` |
| ContractSchema | Archive-assigned UUID | Complete validated `ContractSchema`, including its description |
| Document | Archive-assigned UUID | Complete validated Document record and exact private payload |
| RequestRunRecord | Archive-assigned UUID | Complete request provenance record |
| EvaluationRunRecord | Archive-assigned UUID | Complete offline input-linkage record |
| LocatorRunRecord | Archive-assigned UUID | Complete locator outcome and provenance |
| ContractRunRecord | Archive-assigned UUID | Complete archived Contract outcome and provenance |

Archive-assigned keys use UUID v4 in canonical lowercase hyphenated RFC 4122
text. Their shard is the first two hexadecimal UUID characters. Capture keys use
their existing canonical CaptureId spelling and the first two path-safe key
characters. These rules are part of Archive format 1.

A second public write of a Policy, Plan, ContractSchema, Document, or run record
creates a new immutable snapshot and therefore a new reference. This preserves
exact authored values even when a domain semantic identity intentionally ignores
a field. Capture retains its existing occurrence identity.

The local writer allocates an Archive UUID before staging. A retry inside that
operation reuses the assigned key. If a process dies after publication but
before returning the reference, the first format does not attempt cross-process
retry reconciliation; a later explicit operation-ID design may add that when a
real workflow requires it.

## Data ownership

- Capture owns finalized metadata and exact retained or truncated artifact
  bytes. Its finalized manifest is the only payload-membership authority.
- Document owns its exact normalized evaluator-ready bytes, ID, and profile.
  This is intentionally distinct from Capture artifact bytes: browser DOM and
  accessibility artifacts are normalization inputs, not the canonical Document
  bytes consumed by locators.
- Policy, Plan, and ContractSchema own their semantic encodings. Archive does
  not reinterpret or normalize their fields.
- RequestRunRecord is request provenance. It retains origin-only target facts,
  ordered attempts, every produced/partial/unavailable/unprojectable Document
  outcome, and typed Capture/Document refs.
- EvaluationRunRecord is the offline entrypoint. It contains Capture, Policy,
  Plan, optional ContractSchema, and ordered Document refs. Optional source
  artifact refs preserve provenance but are never treated as Document bytes.
  Writing or reading either record does not schedule acquisition, location,
  extraction, or validation.
- LocatorRunRecord stores the owning `LocateOutcome` exactly, including output
  values, coordinates, order, region lineage, completeness, and terminal state.
- ContractRunRecord stores a closed archived representation of `ContractOutcome<T>`:
  schema-keyed String and Money values with required/optional/many cardinality,
  record issues and evidence, extraction diagnostics, and bounded failures.
  It never stores generated Rust code or arbitrary JSON. Code-independent
  inspection uses the `archived::*` model; when the original Contract type
  is present, `ContractRunRecord::values()` restores validated Rust values and
  checks the embedded schema snapshot automatically.

Archive validates run-record referential integrity before publication and again
when a run is reopened: every typed reference must resolve, effective Policy
identity must agree, each source artifact must belong to the named Capture and
have retained bytes, and each archived Document class must match its requested
projection. Projection records the normalized Document before the only runtime
value is consumed; Archive never attempts to relabel raw browser evidence as a
Document.

## Three independent versions

Callers provide no version fields.

1. **Writer version** is automatic provenance. Each record stamps the exact
   `yosoi-archive` Cargo package name and `CARGO_PKG_VERSION`. It explains which
   release wrote the bytes but never decides whether they are readable.
2. **Record schema version** is a small integer owned independently by each
   record kind. Because first-format envelopes and values fail closed on unknown
   fields, every persisted shape or validation-contract change that an older
   reader cannot accept increments that kind's schema. Ordinary implementation
   changes that preserve accepted bytes do not.
3. **Archive format version** is a small integer for the physical directory and
   publication protocol. The first format is `1` at `.yosoi/archive/v1` and
   changes rarely.

An unsupported format or record schema returns a typed migration-required
error. `Archive::open` never rewrites older data, and the first implementation
contains no migration engine.

## Record envelope

Records are ordinary JSON. A reader decodes the bounded header and retains
`value` as raw JSON, then validates format, kind, schema, and key before asking
the owning domain type to deserialize the value.

```json
{
  "format_version": 1,
  "writer": {
    "package": "yosoi-archive",
    "version": "0.1.0"
  },
  "kind": "policy",
  "schema_version": 1,
  "key": "123e4567-e89b-42d3-a456-426614174000",
  "value": {}
}
```

The record kind already identifies the schema namespace, so the first envelope
does not repeat a free-form schema name. Durable envelope structs deny unknown
fields. A future schema is not accidentally decoded as the current Rust type.

## Typed references

A public reference contains only its closed kind, archive format, and validated
logical key. It never exposes or accepts a filesystem path.

Its textual form is suitable for logs, command arguments, and process handoff:

```text
policy:v1:123e4567-e89b-42d3-a456-426614174000
```

References implement Serde, `Display`, and `FromStr`. Parsing proves structural
validity, not existence; `Archive::read` proves existence and content validity.

## First physical layout

```text
.yosoi/
└── archive/
    └── v1/
        ├── records/
        │   ├── policy/<shard>/<key>.json
        │   ├── plan/<shard>/<key>.json
        │   ├── contract-schema/<shard>/<key>.json
        │   ├── capture/<shard>/<key>.json
        │   ├── document/<shard>/<key>.json
        │   ├── request-run/<shard>/<key>.json
        │   ├── evaluation-run/<shard>/<key>.json
        │   ├── locator-run/<shard>/<key>.json
        │   └── contract-run/<shard>/<key>.json
        ├── captures/<shard>/<capture-key>/payloads/<artifact-id>.bin
        ├── documents/<shard>/<document-key>/payload.bin
        └── staging/
```

Paths follow the kind-specific logical keys above. Existing Web Capture metadata
and private Document record metadata use length and SHA-256 only as corruption
checks. Hashes do not name files or public references; content addressing and
deduplication remain optional future migrations.

Archive format 1 is initially certified on Unix. Non-Unix builds return a typed
unsupported-platform error until their no-replace rename, directory-sync, and
reparse-point behavior is certified.

The caller-selected root may be a shared project directory such as the existing
`.yosoi`; its parent must already exist and its existing permissions are not
changed. The private ownership boundary begins at `.yosoi/archive`. Archive-
created directories use owner-only `0700` permissions and record/payload files
use owner-only `0600` permissions. Opening rejects permissive or symlinked
Archive-owned paths instead of silently weakening the boundary. The selected
root is canonicalized once and all internal paths must remain beneath it.

## Write contract

1. Validate the domain value and select its kind-specific key: CaptureId for a
   Capture, or an Archive-assigned UUID for the other first-project kinds.
2. Encode the record and any owning payload files into a unique staging area.
3. Sync complete staged files before publication.
4. Publish immutable final paths with a platform-certified atomic no-replace
   rename. The first format never uses a hard-link fallback because a crash
   could leave a writable staging alias to committed bytes.
5. Publish the record only after every payload it names is durable.
6. Complete rename plus final/staging directory sync in one non-cancellable
   blocking critical section. A post-rename sync failure returns a typed
   commit-uncertain error containing the record kind and key.
7. Return the typed reference.

An existing equal domain value under the same key and a still-supported record
schema is an idempotent success even when an older Yosoi release wrote it. An
unsupported schema returns migration-required. A different value at the same
logical key is an identity conflict. Last-writer-wins is never valid for
immutable records.

Incomplete staging is invisible to ordinary reads. Known failure paths attempt
cleanup, but process death may leave staging behind. Opening and reading do not
silently delete it.

If a platform or filesystem cannot provide the no-replace primitive, the write
fails explicitly rather than falling back to overwrite or a mutable alias.

## Read contract

1. Validate the typed reference and select its archive-format root.
2. Open exactly one expected record with no-follow semantics, inspect metadata
   from that same handle, and read through a hard byte cap so path replacement
   cannot bypass the record-size limit.
3. Decode and validate the envelope header before the value.
4. Let the owning domain decoder reconstruct and validate the value.
5. For Capture, resolve only manifest-required payloads, verify their declared
   lengths and digests, and finalize through `CaptureBundle::builder`.

Reads perform no acquisition, fallback, repair, migration, evaluation, or
implicit substitution between source, decoded text, rendered DOM, accessibility
tree, JSON, HTML, or XML representations.

## Error boundary

`ArchiveError` is a typed `thiserror` library error. The first vocabulary covers:

- invalid root or reference;
- bounded filesystem I/O operation failure;
- unsupported archive format;
- record migration required, including original writer provenance;
- wrong record kind or logical key;
- malformed or oversized record;
- missing, shortened, or digest-mismatched payload;
- immutable identity conflict.

Production code does not panic and does not flatten these failures into strings.

## Implemented ownership boundaries

The implementation remains split by domain ownership:

- CaptureBundle packaging owns capture records and payload reconstruction.
- Policy, Plan, ContractSchema, and Document own their validated serialized values.
- Requests owns explicit capture-before-projection integration and ordered
  RequestRunRecord projection outcomes.
- EvaluationRunRecord owns fresh-process offline input linkage.

Each lane extends the closed Archive type set without changing the public
`open`/`write`/`read` shape.

## Explicitly deferred

- SQLite, Turso, catalogs, queries, search, tags, aliases, and indexes.
- S3, MinIO, remote providers, replication, reconciliation, and data lakes.
- Public provider traits or a separately shipped in-memory provider.
- Mandatory digest addressing, deduplication, compression, packing, chunking,
  compaction, and garbage collection.
- Automatic acquisition replay, schedules, queues, and workers.
- Opaque imports, export packages, repair, retention, legal holds,
  authorization, and a whole-Archive scanner.
- Generated code, arbitrary application objects, and open-ended JSON Contract values.

## Completion boundary

CAS-309 is complete when CAS-412 can implement the Policy golden journey without
another product-level storage decision. The broader Archive project completes
when a writer process persists one real request, exits, and a separate process
with acquisition disabled rebuilds the exact Documents and produces the same
complete locate, extract, and validate outcome.

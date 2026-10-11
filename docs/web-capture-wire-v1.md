# Web Capture aggregate and wire format v1

Status: implemented pre-release contract

Linear: [CAS-292](https://linear.app/cascadinglabs/issue/CAS-292/define-the-immutable-web-capture-aggregate-and-finalization-rules), [CAS-296](https://linear.app/cascadinglabs/issue/CAS-296/version-and-canonically-serialize-the-web-capture-wire-format)

## Purpose and boundary

`WebCapture` is the immutable terminal aggregate for one concrete web capture
attempt. It composes existing validated acquisition, environment, observation,
provider-capability, artifact-result, and provenance values. It is not a mutable
run record, acquisition API, persisted payload container, Web Session, replay
plan, or derivation recipe.

The Rust type has private fields and no mutating accessors. Both
`WebCapture::finalize` and `Deserialize` run the same cross-field checks. A
caller may clone a capture and construct a different value, but cannot mutate a
finalized capture in place.

## Aggregate shape

The v1 capture object contains exactly these fields:

| Field | Meaning |
| --- | --- |
| `acquisition` | Original target and strategy, observed resolution, and terminal `CaptureReceipt` |
| `environment` | Effective secret-safe HTTP or browser environment |
| `observation` | Bounds, wall-clock correlation window, terminal accounting, and termination evidence |
| `capabilities` | Versioned provider support for the selected acquisition profile |
| `artifacts` | Exhaustive caller requests and typed family results |
| `relationships` | Closed, typed semantic edges between contained artifacts |
| `completeness` | Derived `complete` or `incomplete` aggregate state |

The versioned document envelope is:

```json
{
  "schema_version": 1,
  "capture": { "...": "the validated aggregate above" }
}
```

The complete review fixtures are authoritative examples:

- `crates/yosoi/src/internal/web_capture/integration_tests/fixtures/web-capture/minimal-v1.json`
- `crates/yosoi/src/internal/web_capture/integration_tests/fixtures/web-capture/complete-v1.json`
- `crates/yosoi/src/internal/web_capture/integration_tests/fixtures/web-capture/partial-v1.json`
- `crates/yosoi/src/internal/web_capture/integration_tests/fixtures/web-capture/invalid-v1.json`

Together with the closed Rust types and their `deny_unknown_fields` wire
projections, these fixtures are the v1 reviewable schema artifact. Payload
schemas referenced by artifact provenance remain independently versioned and
are not embedded in this envelope.

## Finalization invariants

Finalization rejects the aggregate unless all of the following hold:

1. The capability acquisition profile matches the request strategy.
2. Direct and context-bound HTTP use an HTTP environment; page-context Fetch
   and document navigation use a browser environment.
3. The capability producer is the HTTP client or browser controller recorded by
   the effective environment.
4. A known browser mode agrees with the document-navigation capability profile.
5. An unrequested artifact family may have either a supported or unsupported
   capability. A requested `unsupported` result requires an unsupported
   capability, and a supported capability cannot report `unsupported`.
6. Produced artifact counts do not exceed `exactly_one` or `at_most_one`
   multiplicity. `many` still requires the non-empty `ArtifactCollection`
   invariant for complete or partial results.
7. Every typed artifact's immediate provenance activity is the containing
   capture activity.
8. Every artifact generation time falls inclusively within the observation
   window. A family for which no artifact exists must instead use an explicit
   unavailable, policy-omitted, unsupported, or not-requested outcome; no
   fabricated artifact timestamp is required.
9. Typed artifact references are unique, and typed manifest records exactly
   equal the receipt outputs. This prevents either representation from silently
   omitting or inventing an output.
10. Every endpoint of every semantic relationship is a family-matching artifact
    in the containing manifest.
11. Serialized `completeness` equals the status derived from terminal facts.

The detailed component constructors continue to enforce their own invariants,
such as URL validity, receipt time ordering, availability/digest agreement,
observation accounting, and request/result agreement.

## Completeness

`incomplete` is a valid finalized state, not a construction error. A capture is
`complete` only when all four conditions hold:

- the activity receipt outcome is `succeeded`;
- observation ended through settlement or a normal controller stop; and
- every requested artifact family has a `complete` result; and
- every produced artifact has complete retained bytes rather than a truncated,
  discarded, or unavailable byte state.

It is therefore explicitly `incomplete` when an activity is partial or
otherwise non-successful, when observation ends because of a deadline, event
limit, byte limit, or interruption, or when any requested family is partial,
unavailable, omitted by policy, or unsupported. The underlying receipt,
termination, and family outcomes preserve the reasons; `completeness` does not
copy them into another potentially contradictory list.

A capture with no requested artifacts can be a valid minimal complete capture
when its activity succeeded and observation stopped normally.

## Equality and identities

Three concepts are intentionally separate:

1. **Rust value equality.** `WebCapture::eq` compares every represented field,
   including occurrence IDs, wall-clock timestamps, and producer-supplied order
   in vectors. It answers whether two in-memory records contain exactly the
   same facts.
2. **Occurrence identity.** `WebCapture::id()` returns the random `CaptureId`
   allocated for the actual attempt. Retries always receive a fresh occurrence
   identity.
3. **Semantic capture identity.** `WebCaptureWire::identity_digest()` hashes an
   explicitly projected and canonically encoded value after excluding volatile
   occurrence/location facts listed below. It answers whether the represented
   capture evidence is semantically equivalent under this v1 policy. It does
   not assert that two artifacts have equal bytes; artifact byte equivalence is
   still `Sha256Digest` on the artifact record.

The semantic identity projection excludes:

- capture and activity occurrence UUIDs (`capture_id`, `activity_id`, and
  receipt `id` fields);
- activity-local artifact ordinals and references (`id`, `artifact_id`,
  `local_id`, and `frame_id` where they represent occurrence-local locations);
- absolute `started_at`, `finished_at`, and `generated_at` timestamps;
- receipt `inputs` and provenance `derived_from`, because they are artifact
  location references and ordered-versus-unordered recipe semantics have not
  been defined;
- `relationships`, because their endpoints are occurrence-local artifact
  references.

The projection retains target and resolution semantics, acquisition kind and
non-location configuration, elapsed timing and bounds, termination and
accounting facts, effective environment values, producer identities and
versions, schemas, artifact families, availability, media type, extent,
sensitivity, reason codes, and content digests.

This intentionally does not introduce a deterministic artifact location,
`DerivedArtifactId`, or replay-plan identity. A later recipe model must decide
operation parameters, input ordering, environment and policy contributions,
and producer compatibility explicitly. `ActivityId` remains fresh for every
execution attempt.

## Canonical JSON contract

`WebCaptureWire::to_canonical_json` is the only v1 byte representation intended
for hashing or golden comparison. Direct `serde_json::to_vec(&capture)` is an
ordinary unversioned Rust serialization and is not this contract.

Canonical v1 JSON uses these rules:

- UTF-8 JSON with no byte-order mark, indentation, trailing whitespace, or
  trailing newline;
- the envelope includes the integer `schema_version` and validated `capture`;
- object member names are ordered lexicographically by Unicode string value;
- strings and integers use `serde_json`'s compact JSON encoding;
- v1 contains no floating-point values; exact decimals such as device scale
  factor are already canonical validated strings;
- arrays preserve order when order may be semantic, notably activity `inputs`
  and provenance `derived_from`;
- arrays named `artifacts`, activity `outputs`, and `relationships` are
  unordered in the domain and are sorted by each element's recursively
  canonical compact JSON representation.

Consequently, captures differing only in non-semantic artifact, output, or
relationship insertion order produce byte-identical canonical JSON. Ordinary
Serde round-trips preserve all represented fields and producer-supplied vector
order; canonical encoding may normalize only the arrays declared unordered
above.

This is the Yosoi Web Capture v1 canonical JSON profile. It should not be
silently relabeled as RFC 8785/JCS; changing escaping, numeric, key-order, or
array-order rules requires a schema-version compatibility decision.

## Compatibility and versioning

`schema_version` is a required positive integer. This implementation supports
only version `1`:

- malformed JSON and invalid v1 domain values fail decoding;
- missing, zero, non-integer, or otherwise invalid version markers fail with a
  version-marker error;
- versions greater than or otherwise different from `1` fail with an actionable
  error reporting both the found and highest supported versions;
- unknown envelope fields, aggregate fields, closed-enum variants, and nested
  fields fail closed;
- `WebCaptureWire::from_json` validates exactly the current v1 shape and has no
  development-shape migration branches.

During pre-release development, the marker remains `1` while this repository
changes rapidly. There are no production consumers and no backward-compatibility
promise yet. Intentional wire changes replace the v1 code, fixtures, and this
document together; obsolete pre-release v1 shapes are rejected rather than
migrated. `decoded_source` and the derived `source_representation` evidence
family are therefore required members of the current v1 artifact-results shape,
including when their status is `not_requested`.

After the first public compatibility commitment, an incompatible wire or
canonicalization change requires a new schema version and an explicit decoder
or migration policy. Until then, do not add speculative legacy readers or v2
names that preserve development-only shapes.

## Out of scope

- persistence containers, compression, signing, or transport framing;
- artifact payload bytes and their independently versioned schemas;
- sessions and transitions between captures;
- deterministic derivation IDs or replay recipes;
- acquisition execution, selectors, and discovery;
- permissive unknown-field or unknown-variant preservation.

# CAS-290: Web artifact families and capture capabilities

Status: implemented type model; provider adapters and artifact payloads remain deferred

Linear: [CAS-290](https://linear.app/cascadinglabs/issue/CAS-290/define-web-artifact-families-and-capture-capabilities)

## Goal

Define which families of evidence a web capture can request and report without
making provider support, request intent, actual production, and retained bytes
mean the same thing. The model remains independent of a browser driver, `wreq`,
payload parser, or persistence implementation.

## Vocabulary boundaries

- **Acquisition strategy** says how one attempt executes. CAS-295 defines direct
  HTTP, context-bound HTTP, page-context Fetch, and document navigation.
- **Browser mode** says whether document navigation was headless or headful. It
  is an environment/configuration fact, not a separate acquisition strategy.
- **Provider capability** says what one explicitly versioned provider profile
  supports. Support does not promise success for an individual attempt.
- **Artifact request** says whether one family is required, optional, or not
  requested.
- **Artifact result** says what actually happened for that family.
- **Artifact availability** and byte extent say what happened to one known
  artifact's serialized bytes.

The three initial product-facing profiles map onto the semantic model as:

```text
simple / wreq -> direct HTTP
headless      -> document navigation + headless browser mode
headful       -> document navigation + headful browser mode
```

A browser-impersonating direct HTTP transport remains direct HTTP. It does not
acquire JavaScript execution, a rendered DOM, accessibility, layout, storage,
visual, or console capabilities.

## Closed first-version families

1. **Source**: original document or resource content.
2. **Rendered DOM**: a serialized live rendered-document observation.
3. **Accessibility tree**: browser accessibility evidence.
4. **Network**: a bounded exchange, resource graph, or network observation.
5. **Cookies**: cookie state scoped to an HTTP session or browser context.
6. **Storage**: web storage other than cookies.
7. **Layout**: geometry, style, text-box, or paint-order evidence.
8. **Visual**: screenshots or other visual page frames.
9. **Runtime diagnostics**: console output and JavaScript runtime failures.

Cookies are separate from storage because direct HTTP can maintain a cookie jar
without implementing browser storage, and because cookie scope and sensitivity
need independent policy. Layout is separate from DOM because DOM capture need
not contain geometry or computed rendering information. Capture environment is
not an artifact; CAS-291 intentionally models it as context required to
interpret artifacts.

`WebArtifact` and `WebArtifactRef` are closed discriminated enums. Each family
has a dedicated Rust wrapper and reference newtype, while `Provenance::schema`
continues to identify the independently versioned payload encoding.

## Provider capability declarations

A `WebProviderCapabilityProfile` identifies:

- the concrete provider and implementation version;
- one semantic acquisition profile;
- an exhaustive `WebArtifactCapabilitySet` containing every initial family.

Each family is either supported with explicit logical multiplicity or
unsupported with a stable reason. Runtime unavailability and policy decisions
are not provider support. Direct and context-bound HTTP profiles reject support
for browser-only DOM, accessibility, storage, layout, visual, and runtime
artifacts during construction and deserialization.

The following is a semantic baseline, not a hard-coded global truth. Concrete
providers must declare their effective support because compile features,
versions, permissions, and configured bounds can change it.

| Evidence | Direct HTTP / `wreq` | Browser navigation, headless | Browser navigation, headful |
| --- | --- | --- | --- |
| Main response source | Supported | Supported when response retention is enabled | Same |
| Browser subresource source | Unsupported as one page graph | Bounded/provider-dependent | Same |
| Rendered DOM | Unsupported | Supported | Supported |
| Accessibility tree | Unsupported | Supported when exposed by the renderer | Same |
| Primary HTTP exchange | Supported | Supported | Supported |
| Browser resource graph | Unsupported | Supported | Supported |
| HTTP cookie jar | Provider/configuration-dependent | Not the browser cookie model | Same |
| Browser-context cookies | Unsupported | Supported | Supported |
| Web storage | Unsupported | Category-dependent | Same |
| Layout | Unsupported | Supported | Supported |
| Visual page capture | Unsupported | Supported | Supported |
| Runtime diagnostics | Unsupported | Supported | Supported |

Context-bound HTTP and page-context Fetch remain representable acquisition
profiles. CAS-290 does not invent detailed capability defaults for them before
a concrete provider consumes those profiles.

## Requests and actual results

`WebArtifactRequestSet` is exhaustive and states `Required`, `Optional`, or
`NotRequested` for every family. It does not duplicate target, environment,
strategy, or observation-window configuration owned by CAS-291, CAS-294, and
CAS-295.

`WebArtifactResults` independently reports one of these states per family:

- `NotRequested`;
- `Complete` with a non-empty typed artifact collection;
- `Partial` with a non-empty typed collection and reason;
- `Unavailable` with a runtime reason;
- `OmittedByPolicy` with a policy reason;
- `Unsupported` with a provider-support reason.

A logical snapshot containing zero entries is still a produced artifact with an
explicit empty payload and digest. No absent collection is interpreted as empty
content. `WebArtifactManifest` validates that requested families cannot report
`NotRequested` and that unrequested families cannot report attempted outcomes.
CAS-292 will additionally validate provider capabilities against actual results
when it constructs the immutable capture aggregate.

## Byte retention and size

The generic `ArtifactRecord` remains authoritative for artifact identity,
retained-byte digest, availability reason, schema, and provenance.
`WebArtifactMetadata` adds:

- canonical lowercase media-type essence;
- sensitivity classification;
- exact retained byte count;
- measured complete or observed byte count when applicable.

`ArtifactByteExtent` must agree with `ArtifactAvailability`:

| Availability | Extent |
| --- | --- |
| Retained | exact complete retained size |
| Truncated | exact retained size plus known or unavailable complete size; a known total must be greater than the retained size |
| Discarded | known or unavailable observed size, with no retained digest |
| Unavailable | no byte extent or digest |

For truncation, the digest continues to cover only the retained bytes.

## Multiplicity and relationships

Multiplicity describes logical artifacts rather than physical storage chunks.
Network, source, rendered DOM, accessibility, cookie, storage, layout, visual,
and runtime evidence may all need deliberately scoped multiple artifacts over
resources, frames, document epochs, or checkpoints. Complete and partial
results use validated non-empty collections.

The first version permits these family-checked semantic relationships:

- rendered DOM represents source content;
- accessibility represents rendered DOM;
- layout represents rendered DOM;
- visual evidence represents layout.

Immediate computational lineage remains in `Provenance::derived_from`. CAS-292
will validate same-capture ownership; later document-epoch and resource
identities can add relationships without converting this vocabulary into an
arbitrary graph.

## Version policy

The first-version domain model fails closed:

- unknown artifact families fail deserialization;
- unknown relationship or outcome variants fail deserialization;
- unknown fields fail deserialization;
- no `Unknown(Value)` escape hatch is present in the typed API.

CAS-296 owns the enclosing schema version and migration entry point. A future
generic package reader may retain unknown payload bytes opaquely, but it must
not present them as a successfully interpreted `WebArtifact`.

## Out of scope

- provider capability probing or negotiation;
- HTTP or browser adapters;
- DOM, AX, network-event, storage, layout, screenshot, or console payloads;
- artifact persistence and chunking;
- capture aggregation and cross-field validation;
- parser and renderer implementations.

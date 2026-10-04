# Contracts and Extractor

Yosoi Contracts turn provenance-rich locator findings into ordinary typed Rust
records without making Contracts responsible for locating evidence.

## Public flow

```rust
let located = Product::locate(&document)?;
let extracted = Product::extract(&located);
let outcome = extracted.validate();
```

Each stage remains independently inspectable:

1. `Product::locate` compiles the pinned Contract locators into the existing
   `Plan` and returns its `LocateOutcome`. Callers can still use
   `Document::locate` independently with any Plan.
2. `Product::extract` groups exact matching outputs into model-shaped
   candidates. A candidate exposes direct fields such as `product.price` and
   `product.categories`.
3. Explicit `.validate()` checks runtime cardinality, converts approved value
types, applies closed semantic rules, and returns typed records or issues.

## Contract declaration

```rust
#[derive(ys::Contract)]
#[ys(
    id = "product",
    description = "One product offered to a buyer",
    root = ys::locator::css("article.product")
)]
struct Product {
    #[ys(
        description = "The product name shown to the buyer",
        locator = ys::locator::css("h2").text()
    )]
    name: String,

    #[ys(
        description = "The currently advertised purchase price",
        locator = PRICE_LOCATOR
    )]
    price: ys::Money,

    #[ys(
        description = "Optional supporting copy",
        locator = ys::locator::css(".subtitle").text()
    )]
    subtitle: Option<String>,

    #[ys(
        description = "Product categories",
        locator = ys::locator::css(".category").text()
    )]
    categories: Vec<String>,
}
```

Rust types express cardinality directly:

- `T` requires exactly one candidate value;
- `Option<T>` accepts zero or one;
- `Vec<T>` accepts zero or more in locator order.

The derive emits portable schema metadata and generated model-shaped candidate
and extracted types. Schema identity uses explicit semantic value IDs, not Rust
source spelling; human descriptions do not change deterministic identity.

Pinned locators are const-friendly data. They may be written inline or
referenced through a reusable constant:

```rust
const PRICE_LOCATOR: ys::PinnedOutputLocator =
    ys::locator::css(".price").text();
```

The first pinned authoring surface supports CSS and decoded-text literal
queries with text projection. Other existing Plan query/projection families
remain available through externally authored Plans until they receive equally
typed pinned declarations.

For a Contract named `Product`, the derive reserves the companion type names
`ProductCandidate` and `ProductExtracted`, the inherent methods `schema`,
`extract`, `extract_with_limit`, `plan`, `locate`, and `root_locator`, the
generated support items `__YS_ROOT_LOCATOR`, `__YS_FIELD_LOCATORS`, and
`__ys_validate_candidate`, and candidate metadata field names `__document_id`
and `__region`.
Authored field visibility is preserved on the generated candidate. The derive
surface is the supported authoring path; the lower-level `Contract` trait hooks
exist for generated cross-crate plumbing and are not a runtime callback API.

## Root and locator identity

Scope is inferred rather than authored separately:

- a pinned contract-level `root` implies `RecordScope::Repeated`;
- no root defaults to `RecordScope::Page`.

Each root match produces one candidate. Generated Plan compilation uses the
Contract ID as its repeated `RegionId` and Contract field IDs as `OutputId`
values. Field locators run relative to a repeated root or against the document
for a page Contract. Inline and referenced locator declarations compile to the
same ordinary `Plan`; there is no second mapping plan.

Repeated-region membership is retained independently from field findings. A
matched empty root therefore becomes a candidate with absent fields: required
fields report `MissingRequired`, optional fields become `None`, and lists remain
empty. It is not collapsed into `NoMatch`.

`Product::plan()` exposes the cached compiled Plan. `Product::locate(&document)`
is the bound convenience. `Product::extract(&located)` remains available for
replay, externally selected compatible plans, and callers that locate
independently.

Unrelated outputs are ignored. Matching outputs with incompatible lineage are
reported as bounded structural diagnostics. Extractor never groups by vector
position, adjacency, fuzzy names, or equal list lengths.

## Candidate inspection

```rust
for product in extracted.candidates() {
    product.price.values();   // projected values awaiting validation
    product.price.evidence(); // exact original Findings
    product.subtitle.is_absent();
}
```

Absence is represented as zero candidate values. Extractor does not choose the
first value, invent defaults, convert values, or validate the Rust record.

## Explicit validation

Validation accepts exact text for `String` and the first semantic `Money` type.
Money accepts the exact grammar `$`, optional `-`, whole ASCII digits, `.`, and
two fractional digits. Surrounding whitespace and locale-specific coercion are
rejected; every negative-form value, including `$-0.00`, is a semantic failure
distinct from parsing.

`ContractOutcome<T>` preserves valid sibling records, invalid candidates,
field issues, extraction diagnostics, and locator terminal states. The strict
`require_all()` convenience succeeds only when every candidate and diagnostic
is clean. It maps a complete `NoMatch` to an empty record vector; callers that
must distinguish no-match from an empty evaluated result should inspect the
full `ContractOutcome` instead.

Public Debug output is structural and redacted. Exact values, coordinates,
document IDs, and source evidence are available only through explicit typed
accessors.

## Bounds

The default Extractor bounds are derived from the locator Policy: every scanned
finding and matching finding is bounded by `max_matches`, while repeated
candidates are bounded by `max_regions`. Values per field, retained evidence,
and diagnostics are checked separately. Validation separately bounds fields,
records, conversions, issues, and retained provenance with checked arithmetic.
Issue provenance is reserved before cloning and retains only the evidence that
caused conversion, semantic, or completeness failures.

## Deferred

Discovery, enrollment generation, dynamic runtime-authored Contracts,
arbitrary conversion or validation callbacks, defaults, nested Contracts,
renaming and joins, cross-document records, Python bindings, persistence,
streaming, and actions are outside this slice.

See the inline and referenced pinned-locator examples:

- `crates/yosoi/examples/contracts_product.rs`
- `crates/yosoi/examples/contracts_page_summary.rs`

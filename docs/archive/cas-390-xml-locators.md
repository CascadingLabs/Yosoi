# CAS-390 XML locator profile

`ys::XmlDocument` parses an immutable `DocumentProfile::source_xml()` payload and evaluates the compiled CSS, XPath, and tree-text operations for that document. It returns the shared `EvaluationOutcome` values, with each finding carrying an exact UTF-8 source byte range and an expanded-name tree path.

```rust
use yosoi::prelude as ys;

let document = ys::Document::try_new(
    "catalog.xml",
    ys::DocumentProfile::source_xml(),
    xml_bytes,
)?;
let query = ys::css("c|Product")?
    .with_namespace("c", "urn:catalog")?;
let plan = ys::plan()
    .emit("products", query.project(ys::descendant_text()))?
    .compile(ys::EvaluationLimits::conservative())?;
let xml = ys::XmlDocument::parse(&document, plan.limits())?;
let result = xml.evaluate(&plan);
```

## Parsing and safety

The parser is pinned to `roxmltree` 0.21.1 with source positions enabled. The selected XML 1.0 profile accepts UTF-8 payloads. It rejects non-empty DTDs, sets `allow_dtd` to false, installs no external-entity resolver, and performs no file or network access. It enforces the caller's node and depth limits within a 2,000,000-node hard safety ceiling.

## CSS subset

CSS matching is case-sensitive. The bounded subset supports element and universal selectors; namespace forms `prefix|name`, `*|name`, `|name`, and their wildcard variants; `#id`, `.class`, `:first-child`, attribute presence and exact equality; descendant and child combinators; and comma-separated selector groups. Attribute selectors without a prefix always use no namespace. Unprefixed element selectors use the query's default namespace when supplied; without one, they match any namespace, as defined by Selectors Level 3. Escapes, other pseudo-classes, sibling combinators, and other selector features are rejected.

Bind prefixes on the `QuerySpec` before compiling the plan. Duplicate, reserved, malformed, and unbound prefixes fail deterministically. The `xml` prefix is predefined. Query bindings are serialized with the query; source-document prefixes do not affect query matching.

The authored expression is preserved byte-for-byte and remains case-sensitive. Binding records are stored in prefix order for deterministic serialization; the compiled matcher resolves each prefix to its namespace URI. Expanded-name coordinates likewise store URIs and local names rather than query or source prefixes.

## XPath subset

The supported grammar is a bounded XPath 1.0 element location-path subset: absolute or relative paths, child and descendant steps, `*`, prefix-qualified element names, attribute presence/equality predicates, numeric position predicates, and `local-name()='value'` predicates. Unprefixed element and attribute names use no namespace, as in XPath 1.0; use explicit query bindings for namespaced names. Function calls beyond `local-name()`, unions, axes other than child/descendant, variables, and general XPath expressions are rejected.

Each path step and predicate consumes the plan's query-step budget. Intermediate and final node sets also obey the match budget.

## Text, projections, and coordinates

Tree-text containment searches the document's mixed descendant text in reading order and returns the deepest matching element for each phrase. Text projection concatenates descendant text and collapses consecutive Unicode whitespace to one ASCII space, trimming the ends. This same normalization is applied to the query phrase.

Attribute projections resolve prefixes from the query bindings. Their reported name is canonicalized as `{namespace-uri}local-name` for namespaced attributes; unprefixed names remain the local name. Node references contain the same coordinate as their finding.

An XML path segment records the namespace URI (or no namespace), local name, and one-based same-expanded-name sibling index. The original source prefix is omitted, so rebinding an equivalent prefix leaves the coordinate unchanged. Findings are emitted in XML document order.

Parsing and evaluation enforce the plan's input, node, depth, query-step, selector-visit, match, and output-byte budgets. The caller's selector-visit budget is additionally bounded by a 20,000,000-operation hard safety ceiling. No partial or truncated XML tree is reported as a complete no-match.

The Criterion bench registers separate `parse`, `locate`, and `end_to_end` cases using the pinned tiny XML catalog. It refuses to start while any CAS-390 RFC-index or ECB advanced oracle is still unlocked.

## Standards references

- [CSS Namespaces Module Level 3](https://www.w3.org/TR/css-namespaces-3/)
- [Selectors Level 3](https://www.w3.org/TR/selectors-3/)
- [XPath 1.0](https://www.w3.org/TR/1999/REC-xpath-19991116/)
- [Namespaces in XML 1.0](https://www.w3.org/TR/xml-names/)

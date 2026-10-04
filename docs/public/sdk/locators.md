---
title: Locators
description: Describe named outputs and inspect the evidence behind each match.
order: 6
---

# Locators

A locator plan says what to select and which values to return. Each output has a name, a query, and a projection.

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "article.html",
        b"<h1>Getting started</h1><a href='/next'>Next</a>".to_vec(),
    )?;
    let plan = ys::Plan::new([
        ys::output("heading", ys::css("h1")?.text())?,
        ys::output("link", ys::css("a")?.attribute("href")?)?,
    ])?;

    match document.locate(&plan) {
        ys::LocateOutcome::Matched { result } => {
            for finding in result.findings() {
                println!("{}: {:?}", finding.output_id(), finding.value());
            }
        }
        ys::LocateOutcome::NoMatch { .. } => println!("No matching evidence"),
        ys::LocateOutcome::Indeterminate { reason_code, .. } => {
            eprintln!("Incomplete evidence: {reason_code}");
        }
        ys::LocateOutcome::Failed { failure } => eprintln!("{failure:?}"),
    }
    Ok(())
}
```

`css("a")` selects elements. `.attribute("href")` chooses what to return. `output("link", ...)` names that value. `Plan::new(...)` checks that all outputs can run against one compatible document class.

## Query families

| Input                             | Constructors                            | Projections                                        |
| --------------------------------- | --------------------------------------- | -------------------------------------------------- |
| [HTML and rendered DOM](html.md)  | `css`, `xpath`                          | `.text()`, `.attribute(name)?`, `.node()`          |
| [XML](xml.md)                     | `css`, `xpath`, with namespace bindings | `.text()`, `.attribute(name)?`, `.node()`          |
| Tree documents                    | `tree_text_contains`                    | `.text()`, `.node()`                               |
| [JSON](json.md)                   | `json_pointer`, `json_path`             | `.value()`                                         |
| [Decoded text](text.md)           | `text_literal`, `regex`                 | `.text()`; regex also supports `.captures(names)?` |
| [Accessibility](accessibility.md) | `role`, `accessible_name`               | `.name()`, `.node()`                               |
| Accessibility                     | `accessibility_text`                    | `.text()`, `.node()`                               |
| Accessibility                     | `accessibility_state`                   | `.node()`                                          |

Unsupported query/projection combinations are errors. For example, JSON uses `.value()`, not `.text()`. A plan cannot combine a CSS output and a JSON Pointer output because no single document class supports both.

## Name outputs once

Output names must be nonempty and unique within the plan. Use names from your application, such as `title` or `price`. For a [Contract](contracts.md), output names must match its field IDs.

Plans do not contain a document identity. Reuse a plan across compatible documents. You can also serialize a plan with Serde; deserialization revalidates its compiled requirements.

## Keep repeated rows together

Use a region when several fields belong to the same card, table row, or list item:

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "catalog.html",
        b"<article><h2>Tea</h2><span class='price'>$4.50</span></article>".to_vec(),
    )?;
    let products = ys::css("article")?.each_as_region("product")?;
    let plan = ys::Plan::new([
        ys::output("name", products.find(ys::css("h2")?).text())?,
        ys::output("price", products.find(ys::css(".price")?).text())?,
    ])?;
    println!("{:?}", document.locate(&plan));
    Ok(())
}
```

Region queries support CSS, XPath, and tree text. Regions are one level deep; nested repeated regions are not supported. A result retains matched regions even when a child field has no finding. That lets Contract validation report a missing field in an existing row.

## Read the evidence

Every `Finding` provides:

| Method            | Meaning                                                      |
| ----------------- | ------------------------------------------------------------ |
| `document_id()`   | Document that supplied the value                             |
| `output_id()`     | Named output that selected it                                |
| `order()`         | Deterministic order in the result                            |
| `value()`         | Text, attribute, JSON value, captures, or node reference     |
| `coordinate()`    | Representation-specific location                             |
| `completeness()`  | Complete, partial, or unknown evidence                       |
| `parent_region()` | Repeated row identity, ordinal, and coordinate, when present |

`NativeCoordinate` distinguishes these locations:

| Variant         | Coordinate data                                                                         |
| --------------- | --------------------------------------------------------------------------------------- |
| `SourceTree`    | A one-based child path, optional source byte range, and optional expanded XML name path |
| `Json`          | A JSON Pointer available through `as_pointer()`                                         |
| `RenderedDom`   | Document epoch and numeric DOM node ID                                                  |
| `Accessibility` | Document epoch and accessibility node ID                                                |
| `DecodedText`   | Both a UTF-8 byte range and a Unicode-scalar range                                      |

Ranges are half-open: the start is included and the end is excluded. Unicode-scalar offsets are not byte offsets or user-perceived character counts. A source byte range is optional; do not infer one from a tree path. XML expanded-name segments retain the namespace URI, local name, and one-based same-name sibling index.

Preserve coordinates with the document identity and profile. A `NodeReference` carries its own document ID and coordinate. It is evidence about an immutable document, not a live browser element. `RegionLineage` similarly preserves the region ID, ordinal, and parent coordinate so findings remain attached to their original row.

Findings, coordinates, plans, and locator outcomes support Serde serialization. For example, with `serde_json`, `serde_json::to_string(&outcome)?` preserves the typed outcome and its evidence rather than only the projected strings.

`Matched` means some regions or findings matched. It does not mean every output matched, nor that every finding is complete. `NoMatch` is a complete absence result for this evaluation. `Indeterminate` means missing evidence prevents that conclusion. `Failed` identifies an invalid plan, parse failure, unsupported combination, or exhausted limit.

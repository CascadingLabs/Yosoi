---
title: Python documents and locators
description: Build immutable documents, compile locator plans in Rust, and inspect evidence.
order: 2
---

# Python documents and locators

`Document` holds immutable input bytes, a stable ID, and a validated profile.
Pass `str` content to encode it as UTF-8, or pass `bytes` to preserve the
original payload. The six supported document classes are:

| Class                | Python constructor                                | Meaning                                            |
| -------------------- | ------------------------------------------------- | -------------------------------------------------- |
| `source_html`        | `Document.html(id, content)`                      | Source HTML using HTML5 parsing                    |
| `source_xml`         | `Document.xml(id, content)`                       | Source XML using the XML profile                   |
| `source_json`        | `Document.from_json(id, content)`                 | Source JSON                                        |
| `source_text`        | `Document.text(id, content)`                      | Decoded UTF-8 text                                 |
| `rendered_dom`       | `Document.rendered_dom(id, epoch, content)`       | Captured rendered DOM with an explicit epoch       |
| `accessibility_tree` | `Document.accessibility_tree(id, epoch, content)` | Captured accessibility tree with an explicit epoch |

The JSON factory is named `from_json` so it does not replace Pydantic's
`model_dump_json()` method. Rendered DOM and accessibility-tree input must use
the corresponding Yosoi schema profile and document epoch. They are explicit
captured representations; local document parsing does not launch a browser to
create them.

## Plans and query families

A `Plan` is a set of named `Output` declarations. Pydantic validates the
declaration shape; the native Rust SDK checks query syntax, resource bounds,
and whether every query/projection pair supports a common document class.
Inspect the compiler's normalized plan with `plan.compiled()`.

Yosoi exposes eleven query families:

| Input family         | Python constructor                    |
| -------------------- | ------------------------------------- |
| CSS                  | `ys.css(expression)`                  |
| XPath                | `ys.xpath(expression)`                |
| Tree text search     | `ys.tree_text_contains(expression)`   |
| JSON Pointer         | `ys.json_pointer(expression)`         |
| JSONPath             | `ys.json_path(expression)`            |
| Accessibility role   | `ys.role(expression)`                 |
| Accessible name      | `ys.accessible_name(expression)`      |
| Accessibility text   | `ys.accessibility_text(expression)`   |
| Accessibility state  | `ys.accessibility_state(name, value)` |
| Literal decoded text | `ys.text_literal(expression)`         |
| Regular expression   | `ys.regex(expression)`                |

Queries support six projections: `.text()`, `.attribute(name)`, `.value()`,
`.node()`, `.name()`, and `.captures(*names)`. A query family only accepts
projections that make sense for its representation. For example, use
`.value()` for JSON and `.name()` for accessibility roles. Rust rejects an
unsupported combination when it compiles the plan.

```python
import yosoi as ys

rows = ys.css("article.product").each_as_region("products")
plan = ys.Plan(
    outputs=[
        ys.output("name", rows.find(ys.css("h2")).text()),
        ys.output("href", rows.find(ys.css("a")).attribute("href")),
    ]
)
```

Regions keep findings attached to their repeated parent, such as a card or
table row. Use `.each_as_region(id)` on a query and `.find(query)` for fields
within it. Regions are one level deep. A matched region stays in the result
even when none of its child outputs produce a finding, so a later Contract can
report missing data for that record.

XML queries can declare namespace bindings on the query. The prefix in the
document is not automatically a query binding:

```python
items = ys.xpath("//p:item").with_namespace("p", "urn:catalog")
```

Use `with_default_namespace(uri)` when an XPath should bind unprefixed element
names to a namespace URI. XML names remain case-sensitive.

## Inspect the result

```python
document = ys.Document.html("page", "<main><h1>Hello</h1></main>")
plan = ys.Plan(outputs=[ys.output("title", ys.css("h1").text())])
outcome = document.locate(plan)

assert outcome.status == "matched"
assert outcome.values("title") == ["Hello"]
```

A `Finding` keeps the document ID, output ID, deterministic order, projected
value, native coordinate, completeness, and optional parent-region lineage.
The coordinate is tied to its immutable document representation; a DOM or
accessibility node reference is not a live browser element.

The outcome statuses retain different meanings:

| Status          | Meaning                                                                                      |
| --------------- | -------------------------------------------------------------------------------------------- |
| `matched`       | At least one region or finding exists; individual outputs may still be absent or incomplete. |
| `no_match`      | Evaluation completed and found no matching region or finding.                                |
| `indeterminate` | Incomplete evidence prevents a complete absence conclusion.                                  |
| `failed`        | Rust reports a typed failure such as an invalid plan or exhausted limit.                     |

`NoMatch`, `Indeterminate`, and `Failed` are not interchangeable empty lists.
Use `outcome.values(output_id)` for a convenience projection, or inspect
`outcome.findings` and each finding when provenance matters.

## Reuse a parsed document

```python
with document.parse() as parsed:
    first = parsed.locate(plan)
    second = parsed.locate(plan)
    assert first == second

assert parsed.closed
```

The parsed Rust handle retains its source document and parse-time policy so you
can run multiple plans without reparsing. Close it explicitly or use the
context-manager form. Calls after closing raise `ClosedResourceError`.

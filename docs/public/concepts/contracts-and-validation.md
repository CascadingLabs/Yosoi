---
title: 'Contracts and validation'
description: 'Describe a record and inspect accepted values and rejected candidates.'
order: 0
---

# Contracts and validation

A Contract describes the typed record a task needs. Its fields have names, descriptions, types and supported evidence bindings.

Rust uses a derived struct. Python uses a Contract model. Both execute extraction and validation through the Rust engine.

## The record's shape

| Meaning                       | Rust        | Python      |
| ----------------------------- | ----------- | ----------- |
| One required text value       | `String`    | `str`       |
| One required money value      | `Money`     | `ys.Money`  |
| An optional supported value   | `Option<T>` | `T \| None` |
| Zero or more supported values | `Vec<T>`    | `list[T]`   |

These supported shapes determine cardinality and conversion. Arbitrary nesting and custom scalar conversion are outside this Contract slice.

## Four stages

1. Describe the record and its field IDs.
2. Locate the evidence with a compatible Plan.
3. Extract candidates, preserving their evidence and region.
4. Validate cardinality, conversion and supported constraints.

Extraction does not make a candidate valid. Validation can return accepted records alongside issues for rejected candidates.

The [Contract programs](../sdk/contracts.md) produce a product record from controlled HTML. The [validation programs](../sdk/validation.md) show one accepted product and another whose required price is missing.

## Choose strict or partial acceptance

Use `require_all()` when the task needs every candidate accepted. Keep the evaluated outcome when the application can use valid records while retaining rejected candidates and their issues.

Inspect the candidate and field evidence when explaining a rejection. This preserves the difference between a missing required field and a value that could not convert.

## Authoring and execution

Python's model provides named fields and inspection tools. Rust constructs validated records. Python validators and defaults do not replace the engine's validation decisions.

A description gives a field meaning. Use a supported static binding or a caller-supplied Plan to connect it to actual evidence.

Follow [Extract structured data](../cookbook/extract-structured-data.md) for the complete task.

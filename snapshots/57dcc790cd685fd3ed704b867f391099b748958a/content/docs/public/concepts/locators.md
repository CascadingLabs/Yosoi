---
title: 'Locators and findings'
description: 'Name queries and keep selected values connected to their evidence.'
order: 0
---

# Locators and findings

A Plan declares named outputs. Each output combines a query with a projection, such as element text, a link attribute, a JSON value or an accessible name.

## Query and projection

The query selects evidence in a representation. The projection says what to read from it.

| Task                                     | Query and projection                 |
| ---------------------------------------- | ------------------------------------ |
| Read an HTML heading                     | CSS with text projection             |
| Read a link target                       | CSS with attribute projection        |
| Read a JSON field                        | JSON Pointer with value projection   |
| Read namespaced XML                      | XPath or CSS with namespace bindings |
| Read an accessible button name           | Role query with name projection      |
| Read an order identifier in decoded text | Regex with named captures            |

The Plan is validated and compiled before evaluation. Unsupported query/projection combinations return errors rather than being treated as no matches.

See [Choose a locator](../cookbook/choose-a-locator.md) for a worked task and [Locators](../sdk/locators.md) for real programs.

## Output names connect the stages

Give outputs names your application or Contract understands. A Contract Plan's output IDs must match its field IDs. A field description explains meaning; it does not automatically discover a query on a website.

## Repeated records

Select a repeated region before locating its child fields. This keeps each product's name and price connected even when one product has no price.

Independent global lists can lose those pairings. A region retains the row's identity and child evidence. The supported region model is one level deep.

## Inspect findings

A finding retains its value, output ID, Document identity, deterministic order, native coordinate, completeness and optional parent region.

Inspect the Locate outcome before using findings. Matched evidence, no match, indeterminate evaluation and failure describe different results. A matched Plan can still have missing outputs.

A [Contract](contracts-and-validation.md) turns field expectations into cardinality and conversion checks.

---
title: Choose a locator
description: Pick the document representation and query that match your task.
order: 0
---

# Choose a locator

Start with the representation you have, then choose a query. The same visible text can appear in HTML source, a rendered DOM, an accessibility tree, or a plain-text document; each has different coordinates and query rules.

| Task                                | Document                   | Query                                                  |
| ----------------------------------- | -------------------------- | ------------------------------------------------------ |
| Read a page heading                 | HTML or rendered DOM       | `css("h1")?.text()`                                    |
| Read a link target                  | HTML or rendered DOM       | `css("a[href]")?.attribute("href")?`                   |
| Extract fields from each card       | HTML, XML, or rendered DOM | A region with child queries, or a Contract with a root |
| Read a namespaced feed element      | XML                        | XPath or CSS with explicit namespace bindings          |
| Read a known JSON field             | JSON                       | `json_pointer("/name")?.value()`                       |
| Read a field from every array item  | JSON                       | `json_path("$.items[*].name")?.value()`                |
| Find an order number in text        | Decoded text               | Regex with a named capture                             |
| Find buttons by their semantic role | Accessibility tree         | `role("button")?.name()`                               |

## Prefer structure when you have it

Use element selectors for HTML and JSON queries for JSON. Regex operates on text documents. Creating a text document from HTML bytes means matching the markup itself, including tags and attributes.

## Keep rows together

If names and prices belong to product cards, select the card as a region first. Separate global name and price lists can lose their pairing when one card lacks a price. A region retains that row's identity even when a child field is missing.

## Choose the right evidence

For content added by JavaScript, request a rendered DOM. For roles and accessible names, request the accessibility tree. A node reference from either is a snapshot coordinate, not a live element handle.

## Inspect the outcome

A matched plan can still have missing outputs. `NoMatch`, `Indeterminate`, and `Failed` convey different facts. If you need one title per row, a Contract can turn that expectation into a cardinality check.

Continue with [Locators](../sdk/locators.md), [Contracts](../sdk/contracts.md), or the [structured extraction recipe](../cookbook/extract-structured-data.md).

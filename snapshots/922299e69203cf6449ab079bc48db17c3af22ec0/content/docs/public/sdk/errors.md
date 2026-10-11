---
title: Errors and troubleshooting
description: Find the stage that failed and keep absence separate from incomplete evidence.
order: 17
---

# Errors and troubleshooting

Start with the layer that returned the problem. Construction errors use `Result`; execution and evaluation also return typed outcomes with their own failure states.

| Stage                              | Inspect                                                       |
| ---------------------------------- | ------------------------------------------------------------- |
| Policy authoring                   | `PolicyError` and `policy.validate()`                         |
| Document construction              | `DocumentError`                                               |
| Query or plan construction         | `QueryError`, `PlanError`, `ContractLocatorError`             |
| Request preparation or setup       | `RequestPreparationError`, `RequestSendError`                 |
| Acquisition                        | `AttemptState`, `AttemptFailureKind`, `diagnostic()`          |
| Document projection                | `DocumentOutcome` and its reason values                       |
| Explicit parse                     | `ParseError`                                                  |
| Locator evaluation                 | `LocateOutcome` and `LocateFailure`                           |
| Contract extraction and validation | `ContractOutcome`, extraction diagnostics, and field issues   |
| Map setup                          | `MapError`                                                    |
| Map execution                      | `termination()`, `sources()`, `frontier()`, and `omissions()` |

## The request returned `Ok`, but there is no document

Inspect every attempt's state, HTTP status, and selected document outcomes. A failed acquisition or unavailable representation is preserved inside the response. `Ok(Response)` does not collapse those states into success.

## The page has an element, but CSS cannot find it

Check the document class first. Direct HTTP gives you source HTML, while a browser's developer tools may show a DOM modified by JavaScript. Request a [rendered DOM](browser.md) when needed. Also check capture timing, selector support, and whether the response was an error or challenge page.

## The plan is rejected

Every output must be compatible with one document class. Use `.value()` for JSON, `.name()` for accessibility roles, and `.text()` for tree text. Output names must be unique. Unsupported syntax is an error rather than an empty result.

## An XML query finds nothing

Check namespace URIs and bind prefixes on each query. XML names are case sensitive. A namespace prefix in the source is not automatically a prefix binding in your query.

## A Contract rejects good-looking data

Inspect the raw candidate values and field issues. A scalar accepts exactly one value; an optional scalar accepts at most one. Money requires an exact supported string format. A JSON string is still a JSON projection and is not automatically converted to a Contract `String`.

## Extraction stops near 64 records

The default Contract extraction path has its own candidate bound of 64. A larger `policy.locators.max_regions` does not increase that later bound. Use `MyContract::extract_with_limit(&located, maximum)` with an explicit bound large enough for the records and their findings, or process smaller document batches. Validation retains its own limits.

## Map returned fewer URLs than expected

Check the seed path, host scope, depth, filters, robots setting, and source outcomes. Then inspect termination, frontier, and omissions. A passive source can be unavailable or sampled. A page in the inventory can remain uninspected.

## A browser operation cannot start

Check the `browser` Cargo feature, a regular Stable browser installation, sandbox support, and display availability for headful mode. The SDK's standard execution path does not expose arbitrary launch-argument overrides.

## Keep absence meaningful

Treat `NoMatch` as no matching evidence in a completed evaluation. Treat `Indeterminate`, `Failed`, partial documents, and rejected records separately. Turning every one of these into an empty vector makes missing data hard to explain.

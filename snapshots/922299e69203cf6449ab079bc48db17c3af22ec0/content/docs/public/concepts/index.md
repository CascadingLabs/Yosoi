---
title: How Yosoi fits together
description: Follow data from discovery through acquisition, location, and validation.
order: 0
---

# How Yosoi fits together

Yosoi separates finding a URL, acquiring its content, selecting evidence, and validating a record. Use the stages you need. A local JSON file can start at Documents; a known URL can start at Requests.

```text
Map → URLs → Request → Documents → Locator Plan → Findings → Contract → Records
             Policy bounds acquisition, parsing, location, and discovery.
```

## Discovery

[Map](../sdk/map.md) finds URLs within a declared scope. It records where each URL came from and whether it was inspected. An inventory entry is a candidate, not proof that a page is reachable or useful.

## Acquisition

[Requests](../sdk/requests.md) run the acquisitions chosen by Policy. Direct HTTP and browser acquisition can produce different evidence for the same URL. A [response](../sdk/responses.md) preserves each attempt and each requested document's outcome.

## Documents

A [Document](../sdk/documents.md) is immutable data with an identity and representation profile. Source HTML, rendered DOM, and an accessibility tree are distinct documents even when they describe the same page.

## Location

A [Plan](../sdk/locators.md) gives names to selected outputs. Its findings keep the value, document identity, native coordinate, repeated-region lineage, and completeness. This lets you trace a record back to its evidence.

## Contracts

A [Contract](../sdk/contracts.md) describes the typed record you want. Extraction groups findings into candidates. Validation checks those candidates and returns valid records alongside issues. A field's Rust type determines both its conversion and cardinality.

## Policy

[Policy](../sdk/policy.md) controls the work an operation may do. A snapshot records the validated choices used for a run. The same URL and Policy can still return different remote content at different times.

## Completion and completeness

Finishing an operation does not prove that its evidence is complete. An acquisition can finish with a partial document, a locator can return some findings while another output is absent, and Map can exhaust its queue without observing every site URL.

Keep the typed outcomes through your workflow. They explain the difference between missing data, incomplete evidence, and work that failed.

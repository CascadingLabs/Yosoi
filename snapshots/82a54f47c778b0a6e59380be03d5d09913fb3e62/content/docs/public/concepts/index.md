---
title: 'Concepts'
description: 'Follow evidence through acquisition, location, validation and browser work.'
order: 0
---

# Concepts

A useful task has an input, some work, and a result you can check. Yosoi keeps evidence and outcomes explicit.

1. Find a candidate URL, or begin with a URL you already know.
2. Acquire its Document, or begin with local bytes.
3. Locate the evidence needed for your task.
4. Extract and validate a typed record when the task needs one.
5. Check the intended result before using it downstream.

Begin at the stage your task needs. A local file needs no discovery or Request.

## Evidence and records

A [Document](../sdk/documents.md) has immutable data, an identity and a representation. Source HTML, rendered DOM and accessibility trees are different evidence.

A [Plan](../sdk/locators.md) names values to locate. Findings preserve where each value came from. Regions keep fields together in repeated records.

A [Contract](../sdk/contracts.md) describes a typed record. Extraction gathers candidates; validation checks cardinality, conversion and supported constraints. Valid records and rejected candidates remain distinguishable.

Rust and Python author these inputs differently, but both execute the shared operations through Rust.

## Acquisition and discovery

A [Request](../sdk/requests.md) acquires a URL under Policy. Its Response can contain failed acquisitions or partial documents.

[Map](../sdk/map.md) inventories scoped URLs. [Search](../sdk/search.md) gets provider candidates. Finding a URL does not prove that its document was acquired.

## Browser work

[Actions and Flows](actions-and-flows.md) describe the recipe. [Sessions and ownership](sessions-and-ownership.md) explain browser lifetime and tab authority.

## Policy and outcomes

[Policy](../sdk/policy.md) bounds work and resource use. [Outcomes](outcomes.md) distinguish operation completion, evidence completeness and business success.

Continue with [SDK](../sdk/index.md) or a [Cookbook](../cookbook/index.md) task.

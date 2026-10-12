---
title: 'Discovery and acquisition'
description: 'Choose how to find URLs and acquire the evidence your task needs.'
order: 0
---

# Discovery and acquisition

Discovery produces candidate URLs. Acquisition obtains evidence from a selected URL. Use each stage when your task needs it.

## Start with your input

| Input                                               | Start with |
| --------------------------------------------------- | ---------- |
| A URL you already know                              | Request    |
| A site whose pages you need to inventory            | Map        |
| A query for search providers                        | Search     |
| HTML, XML, JSON or text already in your application | Document   |

A local document can go directly into a Plan or Contract. A known URL can go directly into a Request.

## Discovery

Map follows a bounded frontier within its declared scope. The inventory keeps observations and relationships explaining how URLs were found. Inspect each page's exploration state to see whether Map inspected it.

Search keeps provider outcomes separate. A response can include candidates from one provider and an unsuccessful outcome from another. Your application chooses which candidates to acquire.

See the real programs in [Map](../sdk/map.md), [Search](../sdk/search.md), and [Discover and fetch](../cookbook/discover-and-fetch.md).

## Acquisition

A Request runs the acquisitions selected by Policy. Direct HTTP can capture source data. Browser acquisition can capture a rendered DOM or accessibility tree.

The acquisition list is ordered. Each authored acquisition runs subject to cancellation and preparation failures. Inspect every attempt and its requested document outcomes.

Choose the evidence needed for the task. A heading present in source HTML can be located from that representation. A heading created by the page's JavaScript may require a rendered capture.

## Keep the results connected

1. Inspect the discovery outcome and choose a candidate.
2. Send a Request under the intended Policy.
3. Inspect its acquisition attempts and available Documents.
4. Pass those Documents into a Plan or Contract.
5. Keep partial reasons and unsuccessful outcomes with the evidence.

Map can retain Documents within a memory budget. [Reuse its captures](../cookbook/discover-and-fetch.md#reuse-maps-captures) when another request is unnecessary.

Map's robots choices apply to its own exploration. A later Request is a separate operation, so apply your application's admission rules to URLs selected downstream.

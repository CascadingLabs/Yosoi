---
title: Search
description: Find candidate URLs through provider-backed search.
order: 2
---

# Search

Search combines query intent, provider routing, and per-provider outcomes in one operation.

## Workflow

1. Choose providers and limits through Policy.
2. Submit a query.
3. Inspect each provider outcome.
4. Fetch selected URLs through Requests.

Search returns candidates; fetching their destination pages is a separate step.

## Handling partial results

One provider can succeed while another is challenged or unavailable. Preserve those outcomes so your application can explain what it found.

Current built-in provider routes are previews pending certification.

Try [CLI Search](../cli/search.md) for a terminal example. Exact Rust signatures belong in the generated API reference.

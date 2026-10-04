---
title: Limits
description: Choose explicit bounds for acquisition, parsing, location, and discovery.
order: 16
---

# Limits

Yosoi bounds work at each stage. Raising a download limit does not also raise parser or locator limits. Change the smallest relevant budget and inspect the outcome when it is exhausted.

## Set a limit

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{AddressableByteLimit, CountLimit, StepLimit};

fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.documents.max_input_bytes = AddressableByteLimit::try_from(2_000_000)?;
    policy.documents.max_depth = StepLimit::try_from(128)?;
    policy.locators.max_matches = CountLimit::try_from(1_000)?;

    let document = ys::Document::html("page.html", b"<h1>Hello</h1>".to_vec())?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    println!("{:?}", document.bind(&policy).locate(&plan));
    Ok(())
}
```

Typed count and byte limits must be positive. Zero does not mean unlimited. Use the corresponding feature's disable setting instead. Map's link and sitemap depth fields are ordinary `u16` values and can be zero.

## Acquisition defaults

These values are from the current `Policy::default()`:

| Policy field                              | Default                                         |
| ----------------------------------------- | ----------------------------------------------- |
| `request.maximum_elapsed`                 | 10,000,000 microseconds: 10 seconds per attempt |
| `request.source.content_coded_bytes`      | 8,000,000 bytes                                 |
| `request.source.representation_bytes`     | 16,000,000 bytes                                |
| `request.source.unicode_utf8_bytes`       | 32,000,000 bytes                                |
| `request.browser.dom_utf8_bytes`          | 16,000,000 bytes                                |
| `request.browser.ax_json_utf8_bytes`      | 16,000,000 bytes                                |
| `request.browser.max_events`              | 10,000                                          |
| `request.browser.max_resources`           | 1,000                                           |
| `request.browser.max_accessibility_nodes` | 10,000                                          |

Content-coded bytes, decoded representation bytes, and derived UTF-8 bytes are separate domains. Compression or character conversion can make their sizes differ.

## Document and locator defaults

| Policy field                   | Default          |
| ------------------------------ | ---------------- |
| `documents.max_input_bytes`    | 67,108,864 bytes |
| `documents.max_nodes`          | 1,000,000        |
| `documents.max_depth`          | 1,024            |
| `locators.max_selector_visits` | 10,000,000       |
| `locators.max_query_bytes`     | 65,536 bytes     |
| `locators.max_query_steps`     | 256              |
| `locators.max_regions`         | 64               |
| `locators.max_matches`         | 100,000          |
| `locators.max_captures`        | 16,384           |
| `locators.max_output_bytes`    | 16,777,216 bytes |

An exhausted locator budget produces `LocateOutcome::Failed` with `LocateFailure::LimitExhausted { limit, maximum, observed }`. It is not a no-match result. Reusable parsed documents keep the Policy budget selected when they were parsed.

Contract extraction and validation have additional bounds. The default extraction path caps candidate records at 64, independently of a custom document Policy. `extract_with_limit(&located, maximum)` replaces extraction's individual budgets with one uniform bound, including the candidate-record budget. Choose it to accommodate both records and their findings.

Default validation allows 1,024 fields and 100,000 records, conversions, issues, and retained provenance items in their respective domains. Low-level validation-limit types are not exported by the SDK's authoring namespaces.

## Map defaults

All these fields live under `policy.map.limits`:

| Field                         | Default                   |
| ----------------------------- | ------------------------- |
| `max_link_depth`              | 2                         |
| `max_hosts`                   | 50                        |
| `max_urls`                    | 500                       |
| `max_relationships`           | 2,000                     |
| `max_observations`            | 4,000                     |
| `max_pending`                 | 500                       |
| `max_requests`                | 100                       |
| `max_sitemaps`                | 20                        |
| `max_sitemap_depth`           | 3                         |
| `max_response_bytes`          | 2,097,152 bytes           |
| `max_total_response_bytes`    | 20,971,520 bytes          |
| `max_retained_document_bytes` | 8,388,608 bytes           |
| `max_concurrency`             | 2                         |
| `maximum_elapsed`             | `Duration::from_secs(30)` |
| `max_url_bytes`               | 8,192 bytes               |
| `max_inventory_bytes`         | 4,194,304 bytes           |
| `max_parser_entries`          | 10,000                    |
| `max_hostname_bytes`          | 253 bytes                 |

Except for the depth and duration fields, Map uses `Budget::new(u32)`. Its overall elapsed limit uses `std::time::Duration`, while request elapsed limits use `MaximumElapsed` in microseconds.

Use [Map's termination, source outcomes, and omissions](map.md) together. Some limits affect retained evidence without removing every discovered URL.

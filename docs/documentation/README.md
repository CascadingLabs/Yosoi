# Documentation foundation

Public pages live in plain Markdown under `docs/public`. The current Rust facade and Python package define supported behavior. The SDK and CLI are the reader's interfaces; design notebooks are historical inputs, not API authority.

## Start here

1. Read [the public authoring rules](../public/AGENTS.md).
2. Find the task in [the page map](page-map.json).
3. Read the listed code authority before changing a behavioral claim.
4. Use [the worker brief](worker-brief.md) and [page template](page-template.md).
5. Record evidence with [the review receipt](review-receipt.md).

The published reading path is **Get Started → Cookbook → SDK → CLI → Concepts**. Reference and release notes follow. Concepts explain shared behavior; SDK pages walk through public calls; Cookbook pages combine tasks and check their results. Separate Python learning pages retain compatible URLs but are outside the main navigation.

## Current delivery

The consolidation includes shared Concepts, CLI task pages, paired Rust/Python examples, and one Cookbook for focused guides and complete recipes. The frontend enhances ordinary Markdown headings with accessible Rust/Python and Cargo/uv controls. Without JavaScript both variants remain readable. Old browser design-review URLs link to supported documentation.

The [quality review](quality-review.md) records local validation and its limits. It is a reviewable documentation pass, not a claim of hosted CI, production deployment or successful execution of every browser example.

## Checks

From the repository root:

```sh
node scripts/docs/check-foundation.mjs
```

For Markdown rendering, navigation, links and focused tests:

```sh
cd scripts/docs
vpr check
```

These gates do not execute SDK examples. Compile Rust examples against the public crate and required features. Check Python examples as normal scripts, then execute deterministic local tasks through the existing UV environment. Validate network and browser stories separately. Keep expensive checks serial.

Use [the roadmap](roadmap.md) for remaining review work and [the quality review](quality-review.md) for current evidence.

---
title: 'Documents and evidence'
description: 'Understand captured bytes, identity, representation and completeness.'
order: 0
---

# Documents and evidence

A Document holds immutable bytes, an identity and a representation profile. A filename or application record ID can serve as its identity. Supplying that identity does not read a file or fetch a URL.

## Choose the representation

| Representation     | Useful evidence                                       |
| ------------------ | ----------------------------------------------------- |
| Source HTML        | Elements, attributes and text in the HTML response    |
| Rendered DOM       | Captured browser structure and document epoch         |
| Accessibility tree | Roles, accessible names, states and tree completeness |
| XML                | Namespace-aware structured content                    |
| JSON               | Typed JSON values and their paths                     |
| Text               | Decoded text, literal matches and regex captures      |

The constructor declares the representation. Parsing and locating evaluate its contents under resource limits. Successful construction preserves the input; inspect later outcomes to establish what evaluation could use.

The [Documents examples](../sdk/documents.md) construct local input and inspect it with real Rust and Python code.

## Captures have identities

A browser capture belongs to a particular document epoch. Its node coordinates describe that retained capture. Acquire fresh evidence when the page has changed before resolving an interaction target.

Two captures of the same URL can contain different bytes or representations. Keep the Document's identity and profile with its data.

## Completeness

A capture can be complete or partial, and a query can operate on only the evidence available to it. Keep the reasons attached to an acquisition or projection rather than turning missing evidence into an ordinary empty result.

A value extracted from incomplete evidence needs the same context. Findings retain coordinates, completeness and repeated-region lineage so a record can be traced back to its source.

## Reuse captured input

1. Save the identity, profile and bytes.
2. Preserve the Plan and Policy when repeating the same evaluation choices matters.
3. Restore the Document with its original profile.
4. Inspect the new locate or Contract outcome.

See [Save and reuse](../cookbook/save-and-reuse.md). Saving bytes supports local re-evaluation; retain acquisition diagnostics separately when the original response was partial.

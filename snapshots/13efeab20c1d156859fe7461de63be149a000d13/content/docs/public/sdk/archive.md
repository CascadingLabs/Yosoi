---
title: Archive availability
description: Preserve document data today and understand the SDK's current archive boundary.
order: 19
---

# Archive availability

The repository has archive and replay implementations, but `yosoi` does not export an `Archive` type, an `archive` module, or archived request execution methods. Responses intentionally expose data and diagnostics without archive handles.

## Save data in your application

For a document you want to inspect again, store its ID, profile, and bytes. Reconstruct it with `Document::from_profile(...)` and apply the same Plan. The [save and reuse recipe](../cookbook/save-and-reuse.md) shows this with ordinary files.

You can serialize a Policy, Plan, and locator outcome through their Serde implementations. Preserve the Policy used for parsing and evaluation if you need to reproduce those choices.

## What this preserves

Saving a document lets you repeat document parsing and location without another network request. It does not save the full request lifecycle, every capture artifact, or a live browser session. Preserve response diagnostics and partial-document reasons separately when they matter to your application.

Use [Map retention](map.md#reuse-retained-documents) to access responses collected during discovery. Retention is in memory and bounded; it is not a disk archive.

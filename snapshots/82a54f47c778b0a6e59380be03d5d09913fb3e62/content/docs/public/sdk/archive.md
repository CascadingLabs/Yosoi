---
title: 'Archive'
description: 'Preserve captured evidence and understand interface boundaries.'
order: 0
---

# Archive

The current Rust facade exports `yosoi::Archive`, `automation_record` and `view`. Browser records can retain receipts and captured evidence after a Session closes.

The current Python bridge does not expose those Rust Archive/View APIs. It can preserve ordinary document metadata and bytes in application-owned files.

## Choose what to preserve

| Need                                             | Approach                                                       |
| ------------------------------------------------ | -------------------------------------------------------------- |
| Re-run location on the same document             | Save identity, profile and bytes                               |
| Inspect stored browser receipts and observations | Use the supported Rust AutomationRecord and Archive APIs       |
| Continue live browser interactions               | Keep a live Session; stored evidence is not live tab authority |

## Local document reuse

Follow [Save and reuse a document](../cookbook/save-and-reuse.md). Preserve Policy and Plan when evaluation must use the same settings. Keep partial-document reasons separately when they matter.

## Replay and fresh execution

Re-evaluating retained evidence does not send another request or recreate a browser Session. Fresh execution can observe changed remote content.

Map's retained documents are bounded in-memory captures. They are not automatically a persistent disk archive.

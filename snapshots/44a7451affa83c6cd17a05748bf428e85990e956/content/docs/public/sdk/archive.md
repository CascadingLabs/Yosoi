---
title: 'Archive'
description: 'Preserve captured evidence and understand interface boundaries.'
order: 0
---

# Archive

The current Rust facade exports `yosoi::Archive`, `automation_record` and `view`. Browser records can retain receipts and captured evidence after a Session closes.

Python exposes `Archive`, `AutomationRecord`, and bounded `View` inspection over the same Rust storage and record validation. `await archive.write(value)` and `await archive.read(reference)` support Documents, compiled Plans, automation records, and Surface outcomes. See [Keeping the evidence](../concepts/keeping-the-evidence.md) for paired runnable examples.

Surface sessions opt into retention through `surface::SessionPolicy.archive` in Rust and `surface.SessionPolicy(archive="enabled")` in Python. Save the returned outcome through the normal Archive callable. `export_file` and `import_file` move that outcome as one self-contained file, with no original store dependency. Follow [Archiving a surface](../concepts/archiving-a-surface.md) for the complete lifecycle and its limits.

The current backend uses local Unix filesystems with private permissions. Windows is unsupported. Each handle keeps no files open between operations. Cancelling a Python await stops waiting while the Rust filesystem operation settles; a write may already have committed without returning a reference.

## Choose what to preserve

| Need                                             | Approach                                                       |
| ------------------------------------------------ | -------------------------------------------------------------- |
| Re-run location on the same document             | Save a Document through Archive                                |
| Inspect stored browser receipts and observations | Use AutomationRecord and Archive in Rust or Python             |
| Continue live browser interactions               | Keep a live Session; stored evidence is not live tab authority |

## Local document reuse

See [Documents](documents.md). Preserve Policy and Plan when evaluation must use the same settings. Keep partial-document reasons separately when they matter.

## Replay and fresh execution

Re-evaluating retained evidence does not send another request or recreate a browser Session. Fresh execution can observe changed remote content.

Map's retained documents are bounded in-memory captures. They are not automatically a persistent disk archive.

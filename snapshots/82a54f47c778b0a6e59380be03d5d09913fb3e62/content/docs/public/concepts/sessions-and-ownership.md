---
title: 'Sessions and ownership'
description: 'Separate browser lifetime, tab authority and execution capacity.'
order: 0
---

# Sessions and ownership

A Session keeps browser resources and state alive. Work gives one caller exclusive control of a tab. Execution capacity bounds active and queued controller operations.

| Piece          | Responsibility                                 |
| -------------- | ---------------------------------------------- |
| Session        | Keep browser resources alive under Policy      |
| Tab            | Identify a page in that Session                |
| Work           | Hold exclusive control of one tab              |
| Execution pool | Bound active and queued controller work        |
| Watcher        | Receive supported receipts without tab control |

## Managed or explicit ownership

A managed [Flow](../sdk/flows.md) acquires resources, executes its recipe and closes resources it owns. Use explicit ownership when dependent tasks need retained browser state.

1. Acquire a Session to own browser state.
2. Acquire Work to control its tab.
3. Run operations that depend on that state while holding Work.
4. Release Work when the dependent sequence ends.
5. Keep the Session alive only if later work needs its state.
6. Close the Session when its lifetime ends.

Releasing Work does not close the Session. A supported condition wait can retain tab authority while yielding execution capacity, allowing another tab to progress.

## Interface boundaries

Both interfaces support Session ownership and borrowed Work. Rust also exposes tab creation and Watcher receipts. The current Python bridge exposes the initial tab, without explicit tab creation or Watcher streams.

See [Sessions](../sdk/sessions/index.md) for code. A Session is not a general job scheduler.

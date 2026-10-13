---
title: "action"
description: "yosoi.browser.action Python API reference."
order: 0
---

`yosoi.browser.action`

```python
async def action(url: str, flow: Flow, *, policy: Policy | None=None, cancellation: CancellationToken | None=None) -> FlowOutcome:
```

Navigate to ``url``, then run the flow with managed SDK cleanup.

Caller cancellation stops subsequent steps and preserves partial/unknown
execution facts. Cancellation is not rollback; managed cleanup still runs.

[Source: python/yosoi/browser.py:2063](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L2063-L2078)

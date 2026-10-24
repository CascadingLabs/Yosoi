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

[Source: python/yosoi/browser.py:2123](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L2123-L2138)

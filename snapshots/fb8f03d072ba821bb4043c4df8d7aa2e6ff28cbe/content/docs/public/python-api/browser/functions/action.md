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

[Source: python/yosoi/browser.py:2222](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L2222-L2237)

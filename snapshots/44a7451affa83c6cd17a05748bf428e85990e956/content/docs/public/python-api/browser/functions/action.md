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

[Source: python/yosoi/browser.py:2222](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L2222-L2237)

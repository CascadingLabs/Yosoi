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

[Source: python/yosoi/browser.py:2123](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2123-L2138)

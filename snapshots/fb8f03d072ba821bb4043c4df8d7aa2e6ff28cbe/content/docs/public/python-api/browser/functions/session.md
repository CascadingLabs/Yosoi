---
title: "session"
description: "yosoi.browser.session Python API reference."
order: 0
---

`yosoi.browser.session`

```python
def session(policy: Policy | None=None, settings: SessionPolicy | None=None, *, cancellation: CancellationToken | None=None) -> Session:
```

Create an async context manager for an explicitly owned browser Session.

[Source: python/yosoi/browser.py:2656](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L2656-L2663)

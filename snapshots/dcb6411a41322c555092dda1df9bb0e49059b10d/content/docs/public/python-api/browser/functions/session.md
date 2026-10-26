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

[Source: python/yosoi/browser.py:2656](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L2656-L2663)

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

[Source: python/yosoi/browser.py:2497](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L2497-L2504)

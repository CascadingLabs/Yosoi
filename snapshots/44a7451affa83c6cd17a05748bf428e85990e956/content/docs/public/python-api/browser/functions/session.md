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

[Source: python/yosoi/browser.py:2656](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L2656-L2663)

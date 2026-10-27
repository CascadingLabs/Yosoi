---
title: "flow"
description: "yosoi.browser.flow Python API reference."
order: 0
---

`yosoi.browser.flow`

```python
def flow(steps: Iterable[Step], *, timeout_ms: int | None=None, on_failure: Continuation | None=None, on_cancellation: Continuation | None=None, capture_on_failure: Literal['disabled', 'screenshot'] | None=None) -> Flow:
```

Build an immutable Flow, retaining Rust defaults unless configured.

[Source: python/yosoi/browser.py:1607](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1607-L1624)

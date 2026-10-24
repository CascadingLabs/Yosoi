---
title: "RequestTrace"
description: "yosoi.map.RequestTrace Python API reference."
order: 0
---

`yosoi.map.RequestTrace`

```python
class RequestTrace(ImmutableModel):
```

Bounded acquisition accounting retained for a Map request.

Attributes:
    target: Requested normalized URL; it can contain user-sensitive path or query
        data.
    status: Observed HTTP status, or None when none was recorded.
    charged_response_bytes: Response bytes charged to operation budgets for the
        attempt.

[Source: python/yosoi/map.py:464](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/map.py#L464-L477)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
target: str
status: int | None
charged_response_bytes: int
```

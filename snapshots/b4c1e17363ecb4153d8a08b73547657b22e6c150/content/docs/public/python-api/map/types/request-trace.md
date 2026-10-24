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

[Source: python/yosoi/map.py:464](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L464-L477)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
target: str
status: int | None
charged_response_bytes: int
```

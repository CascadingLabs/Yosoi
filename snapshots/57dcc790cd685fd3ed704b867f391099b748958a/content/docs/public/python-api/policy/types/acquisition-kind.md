---
title: "AcquisitionKind"
description: "yosoi.policy.AcquisitionKind Python API reference."
order: 0
---

`yosoi.policy.AcquisitionKind`

```python
class AcquisitionKind(ImmutableModel):
```

Resolved acquisition family and optional browser mode.

Attributes:
    kind: direct_http or browser identifies the execution mechanism.
    mode: Headless/headful mode only for browser acquisitions.

[Source: python/yosoi/policy.py:903](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L903-L918)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['direct_http', 'browser']
mode: Literal['headless', 'headful'] | None = None
```

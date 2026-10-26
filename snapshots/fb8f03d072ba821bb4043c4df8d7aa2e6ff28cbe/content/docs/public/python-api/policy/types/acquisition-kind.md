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

[Source: python/yosoi/policy.py:915](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L915-L930)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['direct_http', 'browser']
mode: Literal['headless', 'headful'] | None = None
```

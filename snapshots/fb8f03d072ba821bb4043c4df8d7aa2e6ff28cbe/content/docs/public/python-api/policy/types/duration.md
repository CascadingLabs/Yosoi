---
title: "Duration"
description: "yosoi.policy.Duration Python API reference."
order: 0
---

`yosoi.policy.Duration`

```python
class Duration(Model):
```

Portable elapsed duration with seconds and subsecond nanoseconds.

Attributes:
    seconds: Unsigned u64 whole seconds, not an absolute timestamp.
    nanoseconds: Strict integer remainder below one billion; operation-specific
        positivity is checked separately.

[Source: python/yosoi/policy.py:451](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L451-L461)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
seconds: U64
nanoseconds: Annotated[int, Field(strict=True, ge=0, lt=1000000000)] = 0
```

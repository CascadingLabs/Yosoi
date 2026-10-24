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

[Source: python/yosoi/policy.py:439](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L439-L449)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
seconds: U64
nanoseconds: Annotated[int, Field(strict=True, ge=0, lt=1000000000)] = 0
```

---
title: "Duration"
description: "yosoi.browser.Duration Python API reference."
order: 0
---

`yosoi.browser.Duration`

```python
class Duration(ImmutableModel):
```

Represent a persisted Rust duration with explicit units.

Attributes:
    secs: Whole unsigned seconds.
    nanos: Subsecond nanoseconds from zero through 999,999,999.

[Source: python/yosoi/browser.py:467](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L467-L476)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
secs: U64
nanos: Annotated[int, Field(strict=True, ge=0, lt=1000000000)]
```

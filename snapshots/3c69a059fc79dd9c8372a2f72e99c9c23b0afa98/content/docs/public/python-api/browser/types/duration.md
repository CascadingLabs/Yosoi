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

[Source: python/yosoi/browser.py:467](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L467-L476)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
secs: U64
nanos: Annotated[int, Field(strict=True, ge=0, lt=1000000000)]
```

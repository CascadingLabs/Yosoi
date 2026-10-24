---
title: "Timed"
description: "yosoi.browser.Timed Python API reference."
order: 0
---

`yosoi.browser.Timed`

```python
class Timed(ImmutableModel):
```

Apply a local execution deadline to one action.

Exactly one timeout field must be supplied.

Attributes:
    kind: Wire discriminator identifying this declaration.
    action: Action wrapped by this deadline.
    timeout: Unit-bearing duration; mutually exclusive with timeout_us.
    timeout_us: Legacy positive microsecond deadline; mutually exclusive with
        timeout.

[Source: python/yosoi/browser.py:479](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L479-L501)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['timed'] = 'timed'
action: Step
timeout: Duration | None = None
timeout_us: PositiveU64 | None = None
```

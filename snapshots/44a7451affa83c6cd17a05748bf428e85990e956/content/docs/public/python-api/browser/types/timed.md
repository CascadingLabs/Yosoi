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

[Source: python/yosoi/browser.py:482](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L482-L504)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['timed'] = 'timed'
action: Step
timeout: Duration | None = None
timeout_us: PositiveU64 | None = None
```

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

[Source: python/yosoi/browser.py:482](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L482-L504)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['timed'] = 'timed'
action: Step
timeout: Duration | None = None
timeout_us: PositiveU64 | None = None
```

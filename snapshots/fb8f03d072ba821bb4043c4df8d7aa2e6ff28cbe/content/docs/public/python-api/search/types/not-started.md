---
title: "NotStarted"
description: "yosoi.search.NotStarted Python API reference."
order: 0
---

`yosoi.search.NotStarted`

```python
class NotStarted(ImmutableModel):
```

An authored provider slot retained even though no provider Request started.

Attributes:
    status: Discriminator fixed to not_started for tagged decoding.
    value: Reason execution did not start: uncertified defaults, unavailable
        adapter, unsupported capability, setup failure, cancellation, or deadline.

[Source: python/yosoi/search.py:436](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/search.py#L436-L453)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['not_started']
value: Literal['default_uncertified', 'adapter_unavailable', 'unsupported_capability', 'request_setup_failed', 'cancelled', 'deadline_reached']
```

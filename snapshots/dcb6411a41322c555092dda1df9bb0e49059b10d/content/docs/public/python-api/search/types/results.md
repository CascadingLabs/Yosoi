---
title: "Results"
description: "yosoi.search.Results Python API reference."
order: 0
---

`yosoi.search.Results`

```python
class Results(ImmutableModel):
```

Usable normalized provider results whose coverage may still be partial.

Attributes:
    status: Discriminator fixed to results for tagged decoding.
    value: Normalized provider page; inspect its coverage and issues.

[Source: python/yosoi/search.py:382](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/search.py#L382-L391)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['results']
value: SearchPage
```

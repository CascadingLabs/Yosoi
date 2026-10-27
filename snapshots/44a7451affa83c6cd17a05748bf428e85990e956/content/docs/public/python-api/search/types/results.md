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

[Source: python/yosoi/search.py:382](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/search.py#L382-L391)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['results']
value: SearchPage
```

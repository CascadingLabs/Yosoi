---
title: "LocalPlace"
description: "yosoi.search.LocalPlace Python API reference."
order: 0
---

`yosoi.search.LocalPlace`

```python
class LocalPlace(ImmutableModel):
```

A provider-reported local place, without independent business verification.

Attributes:
    name: Place name displayed by the provider.
    place_url: Validated destination for the place, which has not been fetched.

[Source: python/yosoi/search.py:209](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/search.py#L209-L224)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str = Field(repr=False)
place_url: SearchResultUrl = Field(repr=False)
```

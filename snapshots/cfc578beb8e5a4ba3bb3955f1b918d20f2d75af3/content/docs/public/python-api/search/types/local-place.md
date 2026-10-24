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

[Source: python/yosoi/search.py:209](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L209-L224)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str = Field(repr=False)
place_url: SearchResultUrl = Field(repr=False)
```

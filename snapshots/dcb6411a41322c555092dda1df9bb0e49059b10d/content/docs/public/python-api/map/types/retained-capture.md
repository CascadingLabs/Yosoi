---
title: "RetainedCapture"
description: "yosoi.map.RetainedCapture Python API reference."
order: 0
---

`yosoi.map.RetainedCapture`

```python
class RetainedCapture(ImmutableModel):
```

An acquired response kept alive with its owning Map outcome.

Attributes:
    url: Normalized page or support-source URL associated with the response.
    response: Typed acquired response retaining native capture ownership and
        document access.

[Source: python/yosoi/map.py:578](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/map.py#L578-L588)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
url: str
response: Response
```

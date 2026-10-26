---
title: "Unknown"
description: "yosoi.outcomes.Unknown Python API reference."
order: 0
---

`yosoi.outcomes.Unknown`

```python
class Unknown(ImmutableModel):
```

Evidence completeness could not be established for the requested scope.

Attributes:
    status: Discriminator fixed to unknown for tagged decoding.
    reason_code: Structural explanation of unresolved evidence coverage.

[Source: python/yosoi/outcomes.py:546](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L546-L555)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unknown']
reason_code: str
```

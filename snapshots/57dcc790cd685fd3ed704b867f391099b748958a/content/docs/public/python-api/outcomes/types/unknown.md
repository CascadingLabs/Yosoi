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

[Source: python/yosoi/outcomes.py:546](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L546-L555)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unknown']
reason_code: str
```

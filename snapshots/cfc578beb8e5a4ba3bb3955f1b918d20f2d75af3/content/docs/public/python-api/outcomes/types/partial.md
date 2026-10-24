---
title: "Partial"
description: "yosoi.outcomes.Partial Python API reference."
order: 0
---

`yosoi.outcomes.Partial`

```python
class Partial(ImmutableModel):
```

Known evidence loss prevents an unqualified complete absence claim.

Attributes:
    status: Discriminator fixed to partial for tagged decoding.
    reason_code: Structural explanation of evidence loss, without source excerpts.
    lost_items: Number of omitted items when known; None does not mean zero loss.

[Source: python/yosoi/outcomes.py:532](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L532-L543)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['partial']
reason_code: str
lost_items: U64 | None = None
```

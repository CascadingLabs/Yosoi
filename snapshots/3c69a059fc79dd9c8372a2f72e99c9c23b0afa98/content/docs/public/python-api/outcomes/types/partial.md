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

[Source: python/yosoi/outcomes.py:532](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L532-L543)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['partial']
reason_code: str
lost_items: U64 | None = None
```

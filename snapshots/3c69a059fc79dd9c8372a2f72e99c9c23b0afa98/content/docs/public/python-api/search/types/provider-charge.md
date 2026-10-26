---
title: "ProviderCharge"
description: "yosoi.search.ProviderCharge Python API reference."
order: 0
---

`yosoi.search.ProviderCharge`

```python
class ProviderCharge(ImmutableModel):
```

Reported monetary charge facts; unknown is not evidence of zero cost.

Attributes:
    status: unknown when no charge was reported; known for a reported amount.
    value: Reported amount for a known charge, otherwise None.

[Source: python/yosoi/search.py:534](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L534-L543)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unknown', 'known']
value: ChargeAmount | None = None
```

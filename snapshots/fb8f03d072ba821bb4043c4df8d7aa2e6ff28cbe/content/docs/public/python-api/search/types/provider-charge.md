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

[Source: python/yosoi/search.py:534](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/search.py#L534-L543)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unknown', 'known']
value: ChargeAmount | None = None
```

---
title: "ChargeAmount"
description: "yosoi.search.ChargeAmount Python API reference."
order: 0
---

`yosoi.search.ChargeAmount`

```python
class ChargeAmount(ImmutableModel):
```

Provider-reported monetary amount without conversion or estimation.

Attributes:
    currency: Provider-reported currency identifier.
    amount: Reported amount retained as text to avoid floating-point rounding.

[Source: python/yosoi/search.py:522](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/search.py#L522-L531)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
currency: str
amount: str
```

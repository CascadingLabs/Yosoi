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

[Source: python/yosoi/search.py:522](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L522-L531)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
currency: str
amount: str
```

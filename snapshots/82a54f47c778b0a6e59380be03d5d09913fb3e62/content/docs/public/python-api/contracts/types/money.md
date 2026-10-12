---
title: "Money"
description: "yosoi.contracts.Money Python API reference."
order: 0
---

`yosoi.contracts.Money`

```python
class Money(NativeAuthoringModel):
```

USD monetary scalar represented by integer minor units.

Attributes:
    TYPE_ID: Rust scalar identifier money.usd.
    minor_units: Nonnegative cents within Rust's signed 64-bit representation.
        Python construction rejects negative values; text conversion can report a
        semantic negative-money issue before a record is accepted.
    currency: Discriminator fixed to usd; no exchange-rate conversion occurs.

[Source: python/yosoi/contracts.py:62](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L62-L85)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
TYPE_ID: ClassVar[str] = _native.contract_value_type_id(True)
minor_units: Annotated[int, PydanticField(strict=True, repr=False)]
currency: Literal['usd'] = 'usd'
```

## Methods

### __str__

```python
def __str__(self) -> str:
```

Return the Rust USD amount representation without currency conversion.

[Source: python/yosoi/contracts.py:83](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L83-L85)

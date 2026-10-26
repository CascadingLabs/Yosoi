---
title: "ContractValue"
description: "yosoi.contracts.ContractValue Python API reference."
order: 0
---

`yosoi.contracts.ContractValue`

```python
class ContractValue(Protocol):
```

Identity-only protocol for native Rust Contract scalar types.

Attributes:
    TYPE_ID: Stable scalar identifier included in native transport identity. This
        protocol does not register a Pydantic validator or runtime converter.

[Source: python/yosoi/contracts.py:58](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L58-L66)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
TYPE_ID: ClassVar[str]
```

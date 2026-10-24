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

[Source: python/yosoi/contracts.py:59](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/contracts.py#L59-L67)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
TYPE_ID: ClassVar[str]
```

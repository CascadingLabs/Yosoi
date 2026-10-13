---
title: "ContractValue"
description: "yosoi.contracts.ContractValue Python API reference."
order: 0
---

`yosoi.contracts.ContractValue`

```python
class ContractValue(Protocol):
```

Identity-only protocol for the Rust Contract scalar vocabulary.

Attributes:
    TYPE_ID: Stable scalar identifier included in schema identity. This protocol
        alone does not register a runtime converter.

[Source: python/yosoi/contracts.py:51](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L51-L59)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
TYPE_ID: ClassVar[str]
```

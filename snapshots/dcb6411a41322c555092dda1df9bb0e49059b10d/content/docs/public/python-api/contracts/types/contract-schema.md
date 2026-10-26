---
title: "ContractSchema"
description: "yosoi.contracts.ContractSchema Python API reference."
order: 0
---

`yosoi.contracts.ContractSchema`

```python
class ContractSchema(ImmutableModel):
```

Native transport meaning, scope, and ordered field declarations.

Attributes:
    version: Supported portable format version, currently 1.
    id: Authored record identity, distinct from a document or execution ID.
    description: Nonblank record meaning, excluded from semantic hashing.
    scope: page groups compatible findings into one record; repeated groups by
        parent-region lineage.
    fields: Nonempty ordered fields with unique IDs. Order, IDs, cardinalities, and
        native type IDs contribute to transport identity; Python annotations and
        validators are not represented.

[Source: python/yosoi/contracts.py:137](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L137-L173)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: Literal[1] = 1
id: ContractId
description: str
scope: Literal['page', 'repeated']
fields: tuple[FieldSchema, ...]
```

## Methods

### identity

```python
def identity(self) -> ContractIdentity:
```

Return the Rust-computed semantic schema identity.

Includes version, Contract ID, scope, and ordered field IDs, cardinalities,
and type IDs. Record and field descriptions are excluded from hashing.

Raises:
    ContractError: Schema validation or portable hash accounting fails.

[Source: python/yosoi/contracts.py:162](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L162-L173)

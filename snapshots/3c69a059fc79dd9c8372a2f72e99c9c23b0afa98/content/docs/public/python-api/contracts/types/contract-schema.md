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

[Source: python/yosoi/contracts.py:182](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L182-L218)

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

[Source: python/yosoi/contracts.py:207](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L207-L218)

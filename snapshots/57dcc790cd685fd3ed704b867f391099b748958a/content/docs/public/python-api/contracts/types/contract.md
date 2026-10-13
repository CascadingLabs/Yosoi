---
title: "Contract"
description: "yosoi.contracts.Contract Python API reference."
order: 0
---

`yosoi.contracts.Contract`

```python
class Contract(ImmutableModel):
```

Typed record definition with Rust-owned cardinality and validation.

Attributes:
    root: Optional repeated-region query; None selects page grouping.
    contract_id: Optional schema ID; the class name is used when omitted.
    contract_description: Optional meaning; class docstring or name supplies the
        default. Fields require Field and nonblank descriptions.

[Source: python/yosoi/contracts.py:434](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L434-L523)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
root: ClassVar[Query | None] = None
contract_id: ClassVar[str | None] = None
contract_description: ClassVar[str | None] = None
```

## Methods

### contract_schema

```python
@classmethod
def contract_schema(cls) -> ContractSchema:
```

Return this class's validated schema without document I/O.

Raises:
    ContractError: Fields, scalar annotations, aliases, or processing hooks
        cannot be represented by the supported Rust vocabulary.

[Source: python/yosoi/contracts.py:467](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L467-L474)

### identity

```python
@classmethod
def identity(cls) -> ContractIdentity:
```

Return Rust's semantic identity for this typed schema.

Descriptions do not affect identity. Version, Contract ID, scope, and ordered
field IDs, cardinalities, and scalar type IDs do.

Raises:
    ContractError: The class cannot form a supported portable schema.

[Source: python/yosoi/contracts.py:477](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L477-L486)

### plan

```python
@classmethod
def plan(cls) -> Plan:
```

Return the explicit locator plan pinned by all fields.

Natural-language descriptions do not discover selectors automatically.

Raises:
    ContractError: Fields lack pinned locators or the declaration is invalid.

[Source: python/yosoi/contracts.py:489](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L489-L500)

### extract

```python
@classmethod
def extract(cls: type[T], located: LocateOutcome, *, limits: ExtractionLimits | None=None) -> Extracted[T]:
```

Group located evidence without converting or validating values.

Args:
    located: Locator outcome retaining completeness and failure distinctions.
    limits: Explicit assembly budgets, or None for Rust defaults.

Returns:
    Read-only candidates, diagnostics, or a terminal state. Call validate
    explicitly before treating candidate evidence as accepted records.

Raises:
    ContractError: Declaration or native input setup cannot be represented.

[Source: python/yosoi/contracts.py:503](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L503-L523)

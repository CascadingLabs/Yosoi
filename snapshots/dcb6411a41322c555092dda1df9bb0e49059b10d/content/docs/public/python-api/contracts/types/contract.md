---
title: "Contract"
description: "yosoi.contracts.Contract Python API reference."
order: 0
---

`yosoi.contracts.Contract`

```python
class Contract(Model):
```

Mutable Pydantic record model with native candidate extraction.

Attributes:
    root: Optional repeated-region query; None selects page grouping.
    contract_id: Optional schema ID; the class name is used when omitted.
    contract_description: Optional meaning; class docstring or name supplies the
        default. Field descriptions are optional and do not affect Python
        validation.

[Source: python/yosoi/contracts.py:450](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L450-L584)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
model_config = ConfigDict(hide_input_in_errors=True)
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

Return the native transport schema without document I/O.

Raises:
    ContractError: The class's field identifiers or descriptions cannot be
        represented by the native transport schema.

Python annotations, aliases, defaults, Pydantic configuration, validators,
serializers, and computed fields are not represented here.

[Source: python/yosoi/contracts.py:486](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L486-L496)

### identity

```python
@classmethod
def identity(cls) -> ContractIdentity:
```

Return the Rust identity for this class's native transport shape.

This identity covers version, Contract ID, scope, ordered field IDs,
cardinalities, and native scalar transport types. It does not identify Python
annotations, aliases, defaults, model configuration, or Python validators.

Raises:
    ContractError: The class cannot form a supported portable schema.

[Source: python/yosoi/contracts.py:499](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L499-L509)

### plan

```python
@classmethod
def plan(cls) -> Plan:
```

Return the explicit locator plan pinned by all fields.

Natural-language descriptions do not discover selectors automatically.

Raises:
    ContractError: Fields lack pinned locators or the declaration is invalid.

[Source: python/yosoi/contracts.py:512](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L512-L523)

### assemble

```python
@classmethod
def assemble(cls: type[T], located: LocateOutcome, *, limits: ExtractionLimits | None=None) -> Extracted[T]:
```

Assemble raw native findings for explicit Pydantic validation.

Args:
    located: Locator outcome retaining completeness and failure distinctions.
    limits: Native candidate assembly budgets, or None for Rust defaults.

Returns:
    Raw candidates, diagnostics, or a terminal state. Call ``validate`` to
    produce a report of Pydantic-accepted models and rejected candidates.

Raises:
    ContractError: Declaration or native input setup cannot be represented.

[Source: python/yosoi/contracts.py:526](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L526-L546)

### extract_report

```python
@classmethod
def extract_report(cls: type[T], document: Document | BoundDocument | ParsedDocument, *, policy: ExtractionPolicy | None=None) -> ContractOutcome[T]:
```

Return accepted Pydantic records and every rejected candidate.

The report retains source evidence and terminal outcomes. Convenience
extraction raises according to ``policy``; this method does not raise merely
because a candidate failed Pydantic validation or minimum-record acceptance.

[Source: python/yosoi/contracts.py:549](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L549-L565)

### extract

```python
@classmethod
def extract(cls: type[T], document: Document | BoundDocument | ParsedDocument, *, policy: ExtractionPolicy | None=None) -> list[T]:
```

Locate, validate, and return accepted model instances.

Use ``extract_report`` to inspect rejected candidates, status, and evidence.
Incomplete or terminal native outcomes always raise. A single candidate's
Pydantic error raises as ``ValidationError`` by default; combined rejections
raise ``ContractIssues`` with sanitized details. With
``on_rejected_record='collect'``, only accepted models are returned.

[Source: python/yosoi/contracts.py:568](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L568-L584)

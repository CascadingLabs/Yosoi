---
title: "ValidationLimits"
description: "yosoi.contracts.ValidationLimits Python API reference."
order: 0
---

`yosoi.contracts.ValidationLimits`

```python
class ValidationLimits(ImmutableModel):
```

Native-shaped work budgets applied before Python validation.

Attributes:
    max_fields: Maximum schema fields in one validation pass.
    max_records: Maximum candidate records requiring validation.
    max_conversions: Maximum field inputs, default slots and alias-container
        expansion passed to Pydantic.
    max_issues: Maximum field-level candidate issues retained.
    max_retained_provenance: Maximum candidate and issue evidence references.

[Source: python/yosoi/contracts.py:220](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L220-L246)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_fields: Limit = PydanticField(default_factory=lambda: _validation_default('max_fields'))
max_records: Limit = PydanticField(default_factory=lambda: _validation_default('max_records'))
max_conversions: Limit = PydanticField(default_factory=lambda: _validation_default('max_conversions'))
max_issues: Limit = PydanticField(default_factory=lambda: _validation_default('max_issues'))
max_retained_provenance: Limit = PydanticField(default_factory=lambda: _validation_default('max_retained_provenance'))
```

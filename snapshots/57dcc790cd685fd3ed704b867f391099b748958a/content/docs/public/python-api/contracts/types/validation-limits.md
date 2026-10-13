---
title: "ValidationLimits"
description: "yosoi.contracts.ValidationLimits Python API reference."
order: 0
---

`yosoi.contracts.ValidationLimits`

```python
class ValidationLimits(ImmutableModel):
```

Rust-owned default budgets for conversion and validation accounting.

Attributes:
    max_fields: Maximum schema fields requiring validation.
    max_records: Maximum candidate records requiring validation.
    max_conversions: Maximum charged field conversions.
    max_issues: Maximum retained field rejection issues.
    max_retained_provenance: Maximum retained finding evidence references.

[Source: python/yosoi/contracts.py:240](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L240-L265)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_fields: Limit = PydanticField(default_factory=lambda: _validation_default('max_fields'))
max_records: Limit = PydanticField(default_factory=lambda: _validation_default('max_records'))
max_conversions: Limit = PydanticField(default_factory=lambda: _validation_default('max_conversions'))
max_issues: Limit = PydanticField(default_factory=lambda: _validation_default('max_issues'))
max_retained_provenance: Limit = PydanticField(default_factory=lambda: _validation_default('max_retained_provenance'))
```

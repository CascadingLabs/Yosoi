---
title: "ExtractionPolicy"
description: "yosoi.contracts.ExtractionPolicy Python API reference."
order: 0
---

`yosoi.contracts.ExtractionPolicy`

```python
class ExtractionPolicy(ImmutableModel):
```

Immutable acceptance and native-work limits for Python Contract extraction.

Attributes:
    on_rejected_record: Raise when any candidate fails by default, or collect only
        the accepted models while retaining rejected evidence in an extraction
        report.
    minimum_records: Minimum number of accepted records required by convenience
        extraction. Reports retain results even when this threshold is unmet.
    extraction_limits: Optional Rust limits for raw candidate assembly.
    validation_limits: Optional native-shaped work limits applied before Python
        validators run.

[Source: python/yosoi/contracts.py:253](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L253-L270)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
on_rejected_record: Literal['raise', 'collect'] = 'raise'
minimum_records: Annotated[int, PydanticField(strict=True, ge=0)] = 0
extraction_limits: ExtractionLimits | None = None
validation_limits: ValidationLimits | None = None
```

---
title: "ExtractionLimits"
description: "yosoi.contracts.ExtractionLimits Python API reference."
order: 0
---

`yosoi.contracts.ExtractionLimits`

```python
class ExtractionLimits(ImmutableModel):
```

Nonnegative u64 budgets for candidate assembly.

Attributes:
    max_scanned_regions: Maximum repeated-region lineage entries examined.
    max_scanned_findings: Maximum locator findings examined for field matching.
    max_matching_findings: Maximum findings matching authored Contract fields.
    max_candidates: Maximum candidate records assembled.
    max_values_per_field: Maximum findings retained per field within a candidate.
    max_retained_evidence: Maximum finding evidence references retained across
        candidates.
    max_diagnostics: Maximum nonfatal grouping diagnostics retained.

[Source: python/yosoi/contracts.py:202](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L202-L237)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_scanned_regions: Limit
max_scanned_findings: Limit
max_matching_findings: Limit
max_candidates: Limit
max_values_per_field: Limit
max_retained_evidence: Limit
max_diagnostics: Limit
```

## Methods

### uniform

```python
@classmethod
def uniform(cls, maximum: int) -> Self:
```

Assign the same unsigned limit to every extraction resource.

Args:
    maximum: Strict nonnegative integer fitting u64.

Returns:
    Independent resource fields with the supplied maximum.

Raises:
    pydantic.ValidationError: The maximum is not a strict u64 value.

[Source: python/yosoi/contracts.py:225](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L225-L237)

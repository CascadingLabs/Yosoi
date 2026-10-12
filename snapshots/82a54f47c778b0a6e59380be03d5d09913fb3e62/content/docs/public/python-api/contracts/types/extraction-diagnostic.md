---
title: "ExtractionDiagnostic"
description: "yosoi.contracts.ExtractionDiagnostic Python API reference."
order: 0
---

`yosoi.contracts.ExtractionDiagnostic`

```python
class ExtractionDiagnostic(ImmutableModel):
```

Nonfatal finding-lineage mismatch during candidate grouping.

Attributes:
    kind: Discriminator fixed to incompatible_lineage.
    output: Locator output whose evidence could not join a compatible group.

[Source: python/yosoi/contracts.py:378](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L378-L387)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['incompatible_lineage']
output: str
```

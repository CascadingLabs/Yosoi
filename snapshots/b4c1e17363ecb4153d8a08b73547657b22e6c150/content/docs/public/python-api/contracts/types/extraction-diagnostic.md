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

[Source: python/yosoi/contracts.py:444](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/contracts.py#L444-L453)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['incompatible_lineage']
output: str
```

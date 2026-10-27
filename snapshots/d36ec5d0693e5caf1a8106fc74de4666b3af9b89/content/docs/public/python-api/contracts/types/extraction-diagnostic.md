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

[Source: python/yosoi/contracts.py:394](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L394-L403)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['incompatible_lineage']
output: str
```

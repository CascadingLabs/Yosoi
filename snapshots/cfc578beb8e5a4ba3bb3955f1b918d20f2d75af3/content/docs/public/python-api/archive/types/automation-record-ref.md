---
title: "AutomationRecordRef"
description: "yosoi.archive.AutomationRecordRef Python API reference."
order: 0
---

`yosoi.archive.AutomationRecordRef`

```python
class AutomationRecordRef(ImmutableModel):
```

Portable handle naming one immutable automation record Document.

Attributes:
    version: Logical record version, validated during read.
    document: Exact immutable Document reference in the Rust wire format.

[Source: python/yosoi/archive.py:71](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/archive.py#L71-L85)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: int = Field(strict=True, ge=1, le=2 ** 32 - 1)
document: StrictStr
```

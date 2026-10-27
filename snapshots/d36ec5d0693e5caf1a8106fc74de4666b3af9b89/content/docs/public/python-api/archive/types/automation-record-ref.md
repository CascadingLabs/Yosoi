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

[Source: python/yosoi/archive.py:75](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/archive.py#L75-L89)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: int = Field(strict=True, ge=1, le=2 ** 32 - 1)
document: StrictStr
```

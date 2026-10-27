---
title: "NativeInspection"
description: "yosoi.surface.NativeInspection Python API reference."
order: 0
---

`yosoi.surface.NativeInspection`

```python
class NativeInspection(ImmutableModel):
```

Source-backed detail chunk; concatenate all chunks before parsing JSON.

[Source: python/yosoi/surface.py:190](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L190-L199)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: NativeReference = Field(description='Exact selected evidence.')
media_type: StrictStr = Field(description='Interpretation of content.')
total_bytes: int = Field(description='Complete serialization byte length.')
offset: int = Field(description='Starting UTF-8 byte position.')
content: StrictStr = Field(description='This UTF-8-aligned detail chunk.')
next: Continuation | None = Field(default=None, description='Next detail chunk.')
coverage: Coverage = Field(description='Source completeness.')
```

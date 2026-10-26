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

[Source: python/yosoi/surface.py:183](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L183-L192)

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

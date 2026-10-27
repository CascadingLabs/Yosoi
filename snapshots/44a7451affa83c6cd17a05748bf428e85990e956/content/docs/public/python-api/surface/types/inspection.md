---
title: "Inspection"
description: "yosoi.surface.Inspection Python API reference."
order: 0
---

`yosoi.surface.Inspection`

```python
class Inspection(ImmutableModel):
```

Shared source-backed text fragment; it may be incomplete serialized JSON.

[Source: python/yosoi/surface.py:335](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L335-L346)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: Reference = Field(description='Exact selected evidence.')
media_type: StrictStr = Field(description='Interpretation of content.')
total_bytes: int = Field(description='Complete detail length in UTF-8 bytes.')
offset: int = Field(description='Starting UTF-8 byte position.')
content: StrictStr = Field(description='This detail fragment.')
next: ContinuationToken | None = Field(default=None, description='Opaque next-chunk token.')
coverage: Coverage = Field(description='Completeness of source evidence.')
```

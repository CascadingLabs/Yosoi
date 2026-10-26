---
title: "Event"
description: "yosoi.surface.Event Python API reference."
order: 0
---

`yosoi.surface.Event`

```python
class Event(ImmutableModel):
```

One retained event with optional cursor, watch and reference provenance.

[Source: python/yosoi/surface.py:942](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L942-L955)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
sequence: int = Field(description='Monotonic session-local sequence.')
kind: EventKind = Field(description='Transition category.')
cursor: int | None = Field(description='Affected cursor identity, if any.')
watch: int | None = Field(description='Affected subscription identity, if any.')
before: NativeReference | None = Field(description='Previous evidence, if available.')
after: NativeReference | None = Field(description='Replacement evidence, if available.')
note: StrictStr = Field(description='Recorded explanation of this transition.')
```

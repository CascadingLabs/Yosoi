---
title: "SourceTreeLocation"
description: "yosoi.outcomes.SourceTreeLocation Python API reference."
order: 0
---

`yosoi.outcomes.SourceTreeLocation`

```python
class SourceTreeLocation(ImmutableModel):
```

Tagged HTML/XML tree evidence for a native finding coordinate.

Attributes:
    kind: Discriminator fixed to source_tree for tagged decoding.
    coordinate: Child path and optional exact-byte or expanded-name evidence.

[Source: python/yosoi/outcomes.py:405](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L405-L414)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['source_tree']
coordinate: TreeCoordinate
```

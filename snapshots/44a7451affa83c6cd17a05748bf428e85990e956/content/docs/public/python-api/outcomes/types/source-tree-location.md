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

[Source: python/yosoi/outcomes.py:405](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L405-L414)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['source_tree']
coordinate: TreeCoordinate
```

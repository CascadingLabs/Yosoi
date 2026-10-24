---
title: "Locator"
description: "yosoi.locators.Locator Python API reference."
order: 0
---

`yosoi.locators.Locator`

```python
class Locator(ImmutableModel):
```

Query intent paired with an explicit supported projection.

Attributes:
    query: Query operation and optional repeated-region scope.
    projection: text, attribute, value, node, name, or captures determines emitted
        evidence.
    attribute: Attribute name required for attribute projection, otherwise None.
    captures: Named regex capture selections; Rust checks projection compatibility.

[Source: python/yosoi/locators.py:505](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/locators.py#L505-L524)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
query: Query
projection: ProjectionKind
attribute: str | None = None
captures: tuple[str, ...] = ()
```

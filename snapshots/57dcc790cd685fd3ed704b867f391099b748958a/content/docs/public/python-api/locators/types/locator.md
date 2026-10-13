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

[Source: python/yosoi/locators.py:505](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/locators.py#L505-L524)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
query: Query
projection: ProjectionKind
attribute: str | None = None
captures: tuple[str, ...] = ()
```

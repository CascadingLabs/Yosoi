---
title: "RenderedDomLocation"
description: "yosoi.outcomes.RenderedDomLocation Python API reference."
order: 0
---

`yosoi.outcomes.RenderedDomLocation`

```python
class RenderedDomLocation(ImmutableModel):
```

Tagged rendered-DOM node evidence within a snapshot epoch.

Attributes:
    kind: Discriminator fixed to rendered_dom for tagged decoding.
    coordinate: Snapshot epoch paired with a positive node ID.

[Source: python/yosoi/outcomes.py:429](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L429-L438)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['rendered_dom']
coordinate: DomCoordinate
```

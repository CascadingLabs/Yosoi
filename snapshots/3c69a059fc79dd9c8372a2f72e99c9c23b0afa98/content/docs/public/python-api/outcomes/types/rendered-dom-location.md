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

[Source: python/yosoi/outcomes.py:429](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L429-L438)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['rendered_dom']
coordinate: DomCoordinate
```

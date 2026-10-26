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

[Source: python/yosoi/outcomes.py:429](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/outcomes.py#L429-L438)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['rendered_dom']
coordinate: DomCoordinate
```

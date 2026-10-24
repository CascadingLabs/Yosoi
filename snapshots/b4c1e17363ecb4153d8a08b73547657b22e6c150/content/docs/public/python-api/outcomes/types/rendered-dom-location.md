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

[Source: python/yosoi/outcomes.py:429](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L429-L438)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['rendered_dom']
coordinate: DomCoordinate
```

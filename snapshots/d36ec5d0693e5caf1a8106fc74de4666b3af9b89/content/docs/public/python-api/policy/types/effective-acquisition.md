---
title: "EffectiveAcquisition"
description: "yosoi.policy.EffectiveAcquisition Python API reference."
order: 0
---

`yosoi.policy.EffectiveAcquisition`

```python
class EffectiveAcquisition(ImmutableModel):
```

Resolved acquisition output selection preserving authored intent.

Attributes:
    acquisition: Resolved adapter family and browser mode when applicable.
    authored_selection: Whether output selection was current or exact when authored.
    documents: Concrete document representations selected after resolution.

[Source: python/yosoi/policy.py:933](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L933-L949)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisition: AcquisitionKind
authored_selection: Literal['current', 'exact']
documents: tuple[Literal['response_document', 'rendered_dom', 'accessibility_tree', 'network_tree'], ...]
```

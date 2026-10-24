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

[Source: python/yosoi/policy.py:921](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L921-L937)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisition: AcquisitionKind
authored_selection: Literal['current', 'exact']
documents: tuple[Literal['response_document', 'rendered_dom', 'accessibility_tree', 'network_tree'], ...]
```

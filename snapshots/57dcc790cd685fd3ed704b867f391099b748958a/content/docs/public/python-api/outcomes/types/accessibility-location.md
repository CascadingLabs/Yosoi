---
title: "AccessibilityLocation"
description: "yosoi.outcomes.AccessibilityLocation Python API reference."
order: 0
---

`yosoi.outcomes.AccessibilityLocation`

```python
class AccessibilityLocation(ImmutableModel):
```

Tagged accessibility node evidence within a snapshot epoch.

Attributes:
    kind: Discriminator fixed to accessibility for tagged decoding.
    coordinate: Snapshot epoch paired with the retained node identity.

[Source: python/yosoi/outcomes.py:441](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L441-L450)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['accessibility']
coordinate: AccessibilityCoordinate
```

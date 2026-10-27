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

[Source: python/yosoi/outcomes.py:441](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L441-L450)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['accessibility']
coordinate: AccessibilityCoordinate
```

---
title: "Tuning"
description: "yosoi.policy.Tuning Python API reference."
order: 0
---

`yosoi.policy.Tuning`

```python
class Tuning(Model):
```

Package-owned tuning mode without independent runtime overrides.

Attributes:
    mode: Currently default is the supported tuning vocabulary.

[Source: python/yosoi/policy.py:888](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L888-L899)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
mode: TuningMode = 'default'
```

## Methods

### is_default

```python
def is_default(self) -> bool:
```

Return whether this declaration uses the supported default tuning mode.

[Source: python/yosoi/policy.py:897](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L897-L899)

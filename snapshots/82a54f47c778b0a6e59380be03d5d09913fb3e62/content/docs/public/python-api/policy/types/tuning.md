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

[Source: python/yosoi/policy.py:876](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L876-L887)

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

[Source: python/yosoi/policy.py:885](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L885-L887)

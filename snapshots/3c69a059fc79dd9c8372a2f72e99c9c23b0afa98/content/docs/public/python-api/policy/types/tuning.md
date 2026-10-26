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

[Source: python/yosoi/policy.py:876](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L876-L887)

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

[Source: python/yosoi/policy.py:885](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L885-L887)

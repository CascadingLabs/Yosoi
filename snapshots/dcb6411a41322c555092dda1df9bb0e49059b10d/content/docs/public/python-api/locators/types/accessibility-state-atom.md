---
title: "AccessibilityStateAtom"
description: "yosoi.locators.AccessibilityStateAtom Python API reference."
order: 0
---

`yosoi.locators.AccessibilityStateAtom`

```python
class AccessibilityStateAtom(ImmutableModel):
```

One supported boolean accessibility-state query operand.

Attributes:
    name: Supported state name: expanded or focused.
    value: Required boolean state, not a live browser mutation.

[Source: python/yosoi/locators.py:84](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L84-L93)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: Literal['expanded', 'focused']
value: bool
```

---
title: "accessibility_state"
description: "yosoi.locators.accessibility_state Python API reference."
order: 0
---

`yosoi.locators.accessibility_state`

```python
def accessibility_state(name: AccessibilityStateName, value: bool) -> Query:
```

Declare a boolean accessibility-state query without browser I/O.

Args:
    name: Supported state name, expanded or focused.
    value: Required boolean state.

Returns:
    Accessibility-node query intent for an immutable supported snapshot.

[Source: python/yosoi/locators.py:790](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/locators.py#L790-L800)

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

[Source: python/yosoi/locators.py:790](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/locators.py#L790-L800)

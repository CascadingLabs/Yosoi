---
title: "NativeCoordinate"
description: "yosoi.outcomes.NativeCoordinate Python API reference."
order: 0
---

`yosoi.outcomes.NativeCoordinate`

```python
NativeCoordinate = Annotated[SourceTreeLocation | JsonLocation | RenderedDomLocation | AccessibilityLocation | DecodedTextLocation, Field(discriminator='kind')]
```

Tagged representation-native location: source tree, JSON Pointer, rendered DOM,
accessibility node, or decoded-text ranges. Interpret it with its document identity
and epoch.

[Source: python/yosoi/outcomes.py:465](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L465-L472)

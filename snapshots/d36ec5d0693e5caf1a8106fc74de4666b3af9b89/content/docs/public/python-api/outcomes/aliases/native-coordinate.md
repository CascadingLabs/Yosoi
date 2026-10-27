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

[Source: python/yosoi/outcomes.py:465](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L465-L472)

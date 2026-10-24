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

[Source: python/yosoi/outcomes.py:465](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L465-L472)

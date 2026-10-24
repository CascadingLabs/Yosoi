---
title: "Step"
description: "yosoi.browser.Step Python API reference."
order: 0
---

`yosoi.browser.Step`

```python
Step = Annotated[Navigate | Click | EnterText | Wait | Screenshot | Assert | WaitUntil | Evaluate | Timed | Configured | NestedFlow | LocalRustAssertion | EvaluateFile | EvaluateModule | UntilStep, Field(discriminator='kind')]
```

Tagged browser action, wrapper, nested Flow, or Until declaration.

[Source: python/yosoi/browser.py:612](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L612-L629)

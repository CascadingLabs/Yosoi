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

[Source: python/yosoi/browser.py:612](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L612-L629)

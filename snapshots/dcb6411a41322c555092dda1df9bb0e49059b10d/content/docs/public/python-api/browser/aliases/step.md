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

[Source: python/yosoi/browser.py:615](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L615-L632)

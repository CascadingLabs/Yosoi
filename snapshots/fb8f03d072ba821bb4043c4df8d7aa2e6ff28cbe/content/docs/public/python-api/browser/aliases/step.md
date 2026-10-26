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

[Source: python/yosoi/browser.py:615](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L615-L632)

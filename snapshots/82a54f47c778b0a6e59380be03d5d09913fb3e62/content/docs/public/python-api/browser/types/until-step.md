---
title: "UntilStep"
description: "yosoi.browser.UntilStep Python API reference."
order: 0
---

`yosoi.browser.UntilStep`

```python
class UntilStep(ImmutableModel):
```

Observe an expectation around an optional one-shot trigger.

Observers start before dispatching the trigger. Trigger and observation share a
bounded execution scope; cancellation does not undo the dispatched action.

Attributes:
    kind: Wire discriminator identifying this declaration.
    trigger: Optional Click, EnterText, Evaluate, EvaluateFile, or EvaluateModule
        action.
    expectation: DOM, accessibility, network, Contract, or combined expectation.

[Source: python/yosoi/browser.py:440](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L440-L464)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['until'] = 'until'
trigger: Step | None = None
expectation: UntilExpectation
```

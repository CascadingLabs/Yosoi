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

[Source: python/yosoi/browser.py:443](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L443-L467)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['until'] = 'until'
trigger: Step | None = None
expectation: UntilExpectation
```

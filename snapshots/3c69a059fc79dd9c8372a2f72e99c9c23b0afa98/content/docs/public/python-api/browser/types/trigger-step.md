---
title: "TriggerStep"
description: "yosoi.browser.TriggerStep Python API reference."
order: 0
---

`yosoi.browser.TriggerStep`

```python
class TriggerStep(ImmutableModel):
```

A one-shot action that can be followed by a bounded expectation wait.

[Source: python/yosoi/browser.py:136](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L136-L153)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### until

```python
def until(self, expectation: UntilExpectation | LocalRustAssertion) -> UntilStep:
```

Observe an expectation around this one-shot action.

Args:
    expectation: Typed expectation or locally bound Contract assertion.

Returns:
    Until declaration that registers observers before dispatching this trigger.

[Source: python/yosoi/browser.py:139](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L139-L153)

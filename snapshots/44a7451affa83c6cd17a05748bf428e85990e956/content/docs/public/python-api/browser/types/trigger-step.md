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

[Source: python/yosoi/browser.py:139](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L139-L156)

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

[Source: python/yosoi/browser.py:142](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L142-L156)

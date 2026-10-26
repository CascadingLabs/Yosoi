---
title: "WaitExpectation"
description: "yosoi.browser.WaitExpectation Python API reference."
order: 0
---

`yosoi.browser.WaitExpectation`

```python
class WaitExpectation(ImmutableModel):
```

An expectation that can wait on the current page without a trigger.

[Source: python/yosoi/browser.py:159](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L159-L164)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### until

```python
def until(self) -> UntilStep:
```

Build an Until declaration that observes the page without a trigger.

[Source: python/yosoi/browser.py:162](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L162-L164)

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

[Source: python/yosoi/browser.py:156](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L156-L161)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### until

```python
def until(self) -> UntilStep:
```

Build an Until declaration that observes the page without a trigger.

[Source: python/yosoi/browser.py:159](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L159-L161)

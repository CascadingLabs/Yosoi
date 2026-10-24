---
title: "UntilExpectation"
description: "yosoi.browser.UntilExpectation Python API reference."
order: 0
---

`yosoi.browser.UntilExpectation`

```python
UntilExpectation = Annotated[ConditionExpectation | LocalContractExpectation | AccessibilityExpectation | ResponseExpectation | AllExpectation, Field(discriminator='kind')]
```

Tagged DOM, Contract, accessibility, network, or combined Until expectation.

[Source: python/yosoi/browser.py:429](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L429-L436)

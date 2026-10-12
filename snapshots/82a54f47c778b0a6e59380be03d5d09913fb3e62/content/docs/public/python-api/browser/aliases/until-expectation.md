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

[Source: python/yosoi/browser.py:429](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L429-L436)

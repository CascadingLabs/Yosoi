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

[Source: python/yosoi/browser.py:429](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L429-L436)

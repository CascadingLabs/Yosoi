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

[Source: python/yosoi/browser.py:432](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L432-L439)

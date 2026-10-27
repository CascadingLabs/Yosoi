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

[Source: python/yosoi/browser.py:432](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L432-L439)

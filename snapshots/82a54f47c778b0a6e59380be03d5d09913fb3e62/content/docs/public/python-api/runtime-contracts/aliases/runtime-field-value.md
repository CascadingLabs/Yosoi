---
title: "RuntimeFieldValue"
description: "yosoi.runtime_contracts.RuntimeFieldValue Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeFieldValue`

```python
type RuntimeFieldValue = Annotated[RuntimeExactlyOne | RuntimeZeroOrOne | RuntimeMany, Field(discriminator='cardinality')]
```

Validated runtime field value tagged by its declared cardinality.

[Source: python/yosoi/runtime_contracts.py:144](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L144-L147)

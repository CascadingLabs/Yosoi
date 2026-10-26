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

[Source: python/yosoi/runtime_contracts.py:129](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L129-L132)

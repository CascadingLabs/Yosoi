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

[Source: python/yosoi/runtime_contracts.py:144](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L144-L147)

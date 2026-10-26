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

[Source: python/yosoi/runtime_contracts.py:144](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/runtime_contracts.py#L144-L147)

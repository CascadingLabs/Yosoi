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

[Source: python/yosoi/runtime_contracts.py:129](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L129-L132)

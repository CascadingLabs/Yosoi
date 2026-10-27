---
title: "ArchivedContractFieldValue"
description: "yosoi.runtime_contracts.ArchivedContractFieldValue Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractFieldValue`

```python
type ArchivedContractFieldValue = Annotated[_ArchivedExactlyOne | _ArchivedZeroOrOne | _ArchivedMany, Field(discriminator='cardinality')]
```

Portable field value tagged as required, optional, or repeated.

[Source: python/yosoi/runtime_contracts.py:227](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L227-L230)

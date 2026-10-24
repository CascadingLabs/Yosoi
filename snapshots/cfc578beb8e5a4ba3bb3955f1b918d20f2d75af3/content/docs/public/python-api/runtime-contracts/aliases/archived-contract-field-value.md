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

[Source: python/yosoi/runtime_contracts.py:259](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L259-L262)

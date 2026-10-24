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

[Source: python/yosoi/runtime_contracts.py:259](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L259-L262)

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

[Source: python/yosoi/runtime_contracts.py:227](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L227-L230)

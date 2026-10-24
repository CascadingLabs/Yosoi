---
title: "extract"
description: "yosoi.contracts.extract Python API reference."
order: 0
---

`yosoi.contracts.extract`

```python
def extract[T: 'Contract'](document: Document | BoundDocument | ParsedDocument, contract: type[T], *, policy: ExtractionPolicy | None=None) -> list[T]:
```

Return validated Pydantic models extracted from a document.

[Source: python/yosoi/contracts.py:1598](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/contracts.py#L1598-L1606)

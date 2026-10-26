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

[Source: python/yosoi/contracts.py:1598](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1598-L1606)

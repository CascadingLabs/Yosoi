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

[Source: python/yosoi/contracts.py:1538](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L1538-L1546)

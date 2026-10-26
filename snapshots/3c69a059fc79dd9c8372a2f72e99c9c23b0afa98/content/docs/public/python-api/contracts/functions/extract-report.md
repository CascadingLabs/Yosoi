---
title: "extract_report"
description: "yosoi.contracts.extract_report Python API reference."
order: 0
---

`yosoi.contracts.extract_report`

```python
def extract_report[T: 'Contract'](document: Document | BoundDocument | ParsedDocument, contract: type[T], *, policy: ExtractionPolicy | None=None) -> ContractOutcome[T]:
```

Return a report with accepted models, rejected candidates, and evidence.

[Source: python/yosoi/contracts.py:1609](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1609-L1616)

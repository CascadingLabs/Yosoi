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

[Source: python/yosoi/contracts.py:1549](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1549-L1556)

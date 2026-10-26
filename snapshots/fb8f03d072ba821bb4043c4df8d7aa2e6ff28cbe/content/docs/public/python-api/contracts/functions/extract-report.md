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

[Source: python/yosoi/contracts.py:1609](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/contracts.py#L1609-L1616)

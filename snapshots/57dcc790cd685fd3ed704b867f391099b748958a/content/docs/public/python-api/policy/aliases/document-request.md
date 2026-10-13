---
title: "DocumentRequest"
description: "yosoi.policy.DocumentRequest Python API reference."
order: 0
---

`yosoi.policy.DocumentRequest`

```python
DocumentRequest = Literal['response_document', 'rendered_dom', 'accessibility_tree', 'network_tree']
```

Requested output evidence families. Selection does not guarantee production;
inspect typed partial, unavailable, or unprojectable outcomes.

[Source: python/yosoi/policy.py:46](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L46-L48)

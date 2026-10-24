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

[Source: python/yosoi/policy.py:46](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L46-L48)

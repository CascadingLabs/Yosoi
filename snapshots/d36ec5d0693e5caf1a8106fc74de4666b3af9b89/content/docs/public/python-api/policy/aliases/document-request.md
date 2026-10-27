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

[Source: python/yosoi/policy.py:54](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L54-L56)

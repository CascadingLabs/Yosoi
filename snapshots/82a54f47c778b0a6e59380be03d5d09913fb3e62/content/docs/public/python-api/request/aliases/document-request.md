---
title: "DocumentRequest"
description: "yosoi.request.DocumentRequest Python API reference."
order: 0
---

`yosoi.request.DocumentRequest`

```python
DocumentRequest = Literal['response_document', 'rendered_dom', 'accessibility_tree', 'network_tree']
```

Requested evidence families for an acquisition. A selected family can still be
partial, unavailable, or unprojectable in the returned outcome.

[Source: python/yosoi/request.py:48](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L48-L50)

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

[Source: python/yosoi/request.py:48](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L48-L50)

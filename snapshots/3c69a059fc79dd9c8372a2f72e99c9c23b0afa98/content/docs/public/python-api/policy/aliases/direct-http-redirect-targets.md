---
title: "DirectHttpRedirectTargets"
description: "yosoi.policy.DirectHttpRedirectTargets Python API reference."
order: 0
---

`yosoi.policy.DirectHttpRedirectTargets`

```python
DirectHttpRedirectTargets = Literal['allow_http_and_https', 'same_origin']
```

Redirect admission allows supported HTTP(S) destinations or restricts transitions
to the seed origin. Hop and request budgets apply separately.

[Source: python/yosoi/policy.py:60](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L60-L60)

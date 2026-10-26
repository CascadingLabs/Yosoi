---
title: "Rejection"
description: "yosoi.map.Rejection Python API reference."
order: 0
---

`yosoi.map.Rejection`

```python
Rejection = Literal['invalid_url', 'unsupported_scheme', 'credentials', 'host_scope', 'origin_scope', 'path_scope', 'filtered', 'url_length', 'invalid_host', 'unsupported_domain_scope', 'hostname_length']
```

Admission classifications for invalid URLs, credentials, scope exclusions, filters,
and byte/host limits. Rejection is separate from acquisition failure.

[Source: python/yosoi/map.py:208](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L208-L220)

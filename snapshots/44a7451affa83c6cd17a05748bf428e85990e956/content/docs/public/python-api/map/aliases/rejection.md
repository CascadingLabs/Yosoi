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

[Source: python/yosoi/map.py:208](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/map.py#L208-L220)

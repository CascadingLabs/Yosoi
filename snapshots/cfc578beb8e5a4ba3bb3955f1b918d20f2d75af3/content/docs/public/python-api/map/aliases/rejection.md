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

[Source: python/yosoi/map.py:208](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/map.py#L208-L220)

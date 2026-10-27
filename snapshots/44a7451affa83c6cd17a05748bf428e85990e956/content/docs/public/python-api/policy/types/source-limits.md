---
title: "SourceLimits"
description: "yosoi.policy.SourceLimits Python API reference."
order: 0
---

`yosoi.policy.SourceLimits`

```python
class SourceLimits(Model):
```

Separate retained byte budgets for the HTTP source stages.

Attributes:
    content_coded_bytes: Maximum compressed/content-coded response-body bytes
        admitted.
    representation_bytes: Maximum decoded representation bytes after content
        decoding.
    unicode_utf8_bytes: Maximum UTF-8 bytes in a decoded Unicode text view.

[Source: python/yosoi/policy.py:319](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L319-L338)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
content_coded_bytes: AddressableByteLimitValue = _field('request', 'source', 'content_coded_bytes')
representation_bytes: AddressableByteLimitValue = _field('request', 'source', 'representation_bytes')
unicode_utf8_bytes: AddressableByteLimitValue = _field('request', 'source', 'unicode_utf8_bytes')
```

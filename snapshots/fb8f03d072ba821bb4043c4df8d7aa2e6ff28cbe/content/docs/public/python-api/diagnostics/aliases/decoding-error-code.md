---
title: "DecodingErrorCode"
description: "yosoi.diagnostics.DecodingErrorCode Python API reference."
order: 0
---

`yosoi.diagnostics.DecodingErrorCode`

```python
DecodingErrorCode = Literal['not_classified', 'invalid_charset', 'conflicting_charset', 'unsupported_charset', 'unsupported_utf32', 'unsupported_json_unicode', 'invalid_sequence', 'artifact_metadata']
```

Typed decoding failure or unsupported encoding; no successful text is implied.

[Source: python/yosoi/diagnostics.py:27](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/diagnostics.py#L27-L36)

---
title: "Diagnostic"
description: "yosoi.diagnostics.Diagnostic Python API reference."
order: 0
---

`yosoi.diagnostics.Diagnostic`

```python
type Diagnostic = Annotated[_RequestDiagnosticUnit | _DirectHttpTransportDiagnostic | _BrowserFailureDiagnostic, Field(discriminator='kind')]
```

Request phase failure, transport detail, or browser failure tagged by kind.

[Source: python/yosoi/diagnostics.py:217](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/diagnostics.py#L217-L220)

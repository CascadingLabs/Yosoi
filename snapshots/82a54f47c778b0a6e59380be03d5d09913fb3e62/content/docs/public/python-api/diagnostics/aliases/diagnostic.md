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

[Source: python/yosoi/diagnostics.py:217](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/diagnostics.py#L217-L220)

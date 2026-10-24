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

[Source: python/yosoi/diagnostics.py:217](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/diagnostics.py#L217-L220)

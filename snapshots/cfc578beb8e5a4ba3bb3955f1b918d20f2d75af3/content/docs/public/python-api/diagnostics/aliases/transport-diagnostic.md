---
title: "TransportDiagnostic"
description: "yosoi.diagnostics.TransportDiagnostic Python API reference."
order: 0
---

`yosoi.diagnostics.TransportDiagnostic`

```python
type TransportDiagnostic = Annotated[_DirectHttpTransportUnit | _DirectHttpRedirect, Field(discriminator='kind')]
```

Direct HTTP transport failure or typed redirect rejection details.

[Source: python/yosoi/diagnostics.py:185](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/diagnostics.py#L185-L187)

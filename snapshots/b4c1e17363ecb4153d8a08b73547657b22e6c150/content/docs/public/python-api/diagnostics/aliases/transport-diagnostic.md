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

[Source: python/yosoi/diagnostics.py:185](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/diagnostics.py#L185-L187)

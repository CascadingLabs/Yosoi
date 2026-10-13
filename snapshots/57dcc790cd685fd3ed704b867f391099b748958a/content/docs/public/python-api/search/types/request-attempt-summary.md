---
title: "RequestAttemptSummary"
description: "yosoi.search.RequestAttemptSummary Python API reference."
order: 0
---

`yosoi.search.RequestAttemptSummary`

```python
class RequestAttemptSummary(ImmutableModel):
```

A bounded summary of an underlying acquisition, including recovery attempts.

Attributes:
    request_id: Parent Request identity, including a recovery Request.
    capture_id: Identity allocated to this acquisition capture.
    acquisition: Mechanism selected by the resolved policy.
    http_status: Observed HTTP status, absent when none was recorded.
    source_bytes: Exact retained source-artifact byte count, when recorded.
    diagnostic: Typed bounded failure details, absent when none were recorded.
    terminal: Acquisition completed, failed, or never started; completion does not
        establish provider parsing success.

[Source: python/yosoi/search.py:499](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/search.py#L499-L519)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
request_id: str
capture_id: str
acquisition: AcquisitionKind
http_status: int | None
source_bytes: int | None
diagnostic: SearchAttemptDiagnostic | None
terminal: Literal['completed', 'failed', 'not_started']
```

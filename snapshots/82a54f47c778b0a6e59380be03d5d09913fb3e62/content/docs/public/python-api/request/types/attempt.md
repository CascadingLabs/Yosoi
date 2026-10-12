---
title: "Attempt"
description: "yosoi.request.Attempt Python API reference."
order: 0
---

`yosoi.request.Attempt`

```python
class Attempt(ImmutableModel):
```

Typed acquisition outcome retained in authored policy order.

Attributes:
    capture_id: Identity allocated to this capture occurrence.
    acquisition: Direct HTTP or browser mechanism selected by the policy.
    authored_selection: current resolves package defaults; exact retains explicitly
        authored selection.
    requested_target: Original request target; it can contain user-sensitive path or
        query text.
    http_status: Observed HTTP status, or None when no status was recorded.
    state: completed, failed, or not_started describes acquisition execution, not
        HTTP business success or completeness of every document.
    failure_kind: Typed failure classification when an attempt failed.
    not_started_reason: Reason acquisition did not start, when applicable.
    diagnostic: Typed structural diagnostics without substituting them for document
        evidence.
    documents: One outcome per authored document representation in acquisition
        order.

[Source: python/yosoi/request.py:182](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L182-L212)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture_id: str
acquisition: AcquisitionKind
authored_selection: Literal['current', 'exact']
requested_target: str
http_status: int | None
state: Literal['completed', 'failed', 'not_started']
failure_kind: AttemptFailureKind | None
not_started_reason: NotStartedReason | None
diagnostic: Diagnostic | None
documents: tuple[AttemptDocument, ...]
```

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
    content_type: Bounded declared Direct HTTP Content-Type, including parameters.
        None when absent, invalid, duplicated, oversized, or unavailable; this
        declaration does not verify the file format.
    body: Complete retained Direct HTTP representation bytes after content
        decoding, before character decoding. Includes binary images without
        requiring a Document. None for incomplete/unavailable bodies,
        browser acquisitions, or omitted response-document selection. An empty
        retained body is b"". HTTP errors can still have bodies; inspect status.
        Payload bytes are excluded from repr and model dumps.
    state: completed, failed, or not_started describes acquisition execution, not
        HTTP business success or completeness of every document.
    failure_kind: Typed failure classification when an attempt failed.
    not_started_reason: Reason acquisition did not start, when applicable.
    diagnostic: Typed structural diagnostics without substituting them for document
        evidence.
    documents: One outcome per authored document representation in acquisition
        order.

[Source: python/yosoi/request.py:182](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/request.py#L182-L223)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture_id: str
acquisition: AcquisitionKind
authored_selection: Literal['current', 'exact']
requested_target: str
http_status: int | None
content_type: str | None = None
body: bytes | None = Field(default=None, repr=False, exclude=True)
state: Literal['completed', 'failed', 'not_started']
failure_kind: AttemptFailureKind | None
not_started_reason: NotStartedReason | None
diagnostic: Diagnostic | None
documents: tuple[AttemptDocument, ...]
```

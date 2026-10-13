---
title: "Response"
description: "yosoi.request.Response Python API reference."
order: 0
---

`yosoi.request.Response`

```python
class Response(ImmutableModel):
```

Completed and failed acquisition evidence with retained native ownership.

Attributes:
    request_id: Identity of the prepared request producing these outcomes.
    requested_target: Requested target text; repr redacts it but direct access can
        expose user content.
    policy_snapshot: Resolved immutable policy snapshot fixed during preparation.
    termination: completed means execution did not observe caller cancellation, not
        that every acquisition succeeded. cancelled retains prior outcomes and later
        unstarted attempts.
    attempts: One typed outcome per authored acquisition in policy order, including
        failures and work that never started.

[Source: python/yosoi/request.py:215](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L215-L276)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
request_id: str
requested_target: str = Field(repr=False)
policy_snapshot: PolicySnapshot
termination: Literal['completed', 'cancelled']
attempts: tuple[Attempt, ...] = Field(repr=False)
```

## Methods

### documents

```python
@property
def documents(self) -> tuple[Document, ...]:
```

Collect all retained documents in acquisition and request order.

Includes documents from partial outcomes when present. Inspect attempts to
retain requested representation, failure, and completeness distinctions;
this convenience tuple alone cannot establish success or complete absence.

[Source: python/yosoi/request.py:264](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L264-L276)

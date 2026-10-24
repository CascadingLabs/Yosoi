---
title: "BoundDocument"
description: "yosoi.documents.BoundDocument Python API reference."
order: 0
---

`yosoi.documents.BoundDocument`

```python
class BoundDocument:
```

Retained document paired with a serialized policy snapshot.

Attributes:
    document: Immutable document owner; later caller-policy edits do not change the
        binding.

[Source: python/yosoi/documents.py:421](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L421-L464)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, document: Document, policy: Policy) -> None:
```

Retain a document and snapshot a policy without acquisition I/O.

Args:
    document: Immutable payload owner to retain.
    policy: Complete declaration to serialize for parsing and locating.

[Source: python/yosoi/documents.py:429](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L429-L437)

### policy

```python
@property
def policy(self) -> Policy:
```

Return a policy copy whose edits do not change this binding.

[Source: python/yosoi/documents.py:440](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L440-L442)

### locate

```python
def locate(self, plan: Plan) -> LocateOutcome:
```

Execute the authored plan using the bound policy.

Args:
    plan: Outputs and projections to evaluate against retained bytes.

Returns:
    Typed outcome preserving matches, absence, incompleteness, or failure.

[Source: python/yosoi/documents.py:444](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L444-L453)

### parse

```python
def parse(self) -> ParsedDocument:
```

Create a reusable parse using the bound resource limits.

Returns:
    A parse owner to close explicitly or use as a context manager.

Raises:
    ParseError: Parsing or configured resource checks reject the payload.

[Source: python/yosoi/documents.py:455](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L455-L464)

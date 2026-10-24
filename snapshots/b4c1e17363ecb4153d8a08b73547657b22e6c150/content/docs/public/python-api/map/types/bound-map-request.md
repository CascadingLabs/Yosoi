---
title: "BoundMapRequest"
description: "yosoi.map.BoundMapRequest Python API reference."
order: 0
---

`yosoi.map.BoundMapRequest`

```python
class BoundMapRequest:
```

A discovery request bound to a serialized policy snapshot.

Attributes:
    request: Retained authored seed request. Later caller-policy edits do not change
        the snapshot.

[Source: python/yosoi/map.py:697](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L697-L747)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, request: MapRequest, policy: Policy) -> None:
```

Retain the request and snapshot its policy without network I/O.

Args:
    request: Authored seed request to retain.
    policy: Complete declaration to serialize for later checks and sends.

[Source: python/yosoi/map.py:705](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L705-L713)

### policy

```python
@property
def policy(self) -> Policy:
```

Return a policy copy whose edits do not change this binding.

[Source: python/yosoi/map.py:716](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L716-L718)

### check

```python
def check(self) -> None:
```

Validate seed and bound-policy admission without network I/O.

Raises:
    MapError: The seed, scope, policy, or acquisition setup is invalid.

[Source: python/yosoi/map.py:720](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L720-L726)

### send

```python
async def send(self, *, cancellation: CancellationToken | None=None) -> MapOutcome:
```

Discover with the bound policy and retain evidence on cancellation.

Args:
    cancellation: Optional cooperative token shared with other operations.

Returns:
    Typed inventory and acquisition owners, including failed or sampled sources
    and unfinished work. Exhaustion is not proof of exhaustive site coverage.

Raises:
    MapError: Seed validation, policy resolution, or execution setup fails.
    pydantic.ValidationError: Native data cannot form a typed result.

[Source: python/yosoi/map.py:728](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L728-L747)

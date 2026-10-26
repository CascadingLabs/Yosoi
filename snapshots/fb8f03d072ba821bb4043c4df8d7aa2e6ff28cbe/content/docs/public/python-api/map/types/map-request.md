---
title: "MapRequest"
description: "yosoi.map.MapRequest Python API reference."
order: 0
---

`yosoi.map.MapRequest`

```python
class MapRequest(NativeAuthoringModel):
```

Authored seed intent with validation deferred to checking or sending.

Attributes:
    seed: Caller seed text; creating this model does not send network requests.

[Source: python/yosoi/map.py:643](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L643-L694)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
seed: str = Field(repr=False)
```

## Methods

### model_post_init

```python
def model_post_init(self, context: object) -> None:
```

Retain authored seed intent natively without acquiring pages.

[Source: python/yosoi/map.py:653](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L653-L655)

### check

```python
def check(self) -> None:
```

Validate seed and package-default policy without network I/O.

Raises:
    MapError: The seed, scope, policy, or acquisition setup is invalid.

[Source: python/yosoi/map.py:657](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L657-L663)

### bind

```python
def bind(self, policy: Policy) -> BoundMapRequest:
```

Snapshot a complete policy declaration for later discovery.

Args:
    policy: Complete declaration to serialize at binding time.

Returns:
    A binding unaffected by later edits to the caller policy.

[Source: python/yosoi/map.py:665](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L665-L674)

### send

```python
async def send(self, *, cancellation: CancellationToken | None=None) -> MapOutcome:
```

Discover within package defaults while retaining typed evidence.

Args:
    cancellation: Optional cooperative token shared with other operations.
        Observed cancellation stops further work and retains existing outcomes.

Returns:
    Discovery evidence and acquisition owners. Inspect source states, frontier,
    omissions, and termination before claiming completeness.

Raises:
    MapError: Seed validation, policy resolution, or execution setup fails.
    pydantic.ValidationError: Native data cannot form a typed result.

[Source: python/yosoi/map.py:676](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L676-L694)

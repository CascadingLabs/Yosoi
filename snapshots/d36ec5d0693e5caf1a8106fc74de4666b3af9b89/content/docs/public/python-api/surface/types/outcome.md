---
title: "Outcome"
description: "yosoi.surface.Outcome Python API reference."
order: 0
---

`yosoi.surface.Outcome`

```python
class Outcome(ImmutableModel):
```

Portable evidence and receipts, without live session or action authority.

[Source: python/yosoi/surface.py:994](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L994-L1084)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: Literal[1] = Field(default=1, description='Logical outcome schema version.')
record: AutomationRecord = Field(description='Ordered original operation certainty and observations.')
sources: tuple[ArchivedSource, ...] = Field(default=(), description='Retained original sources and materialized evidence.')
plans: tuple[Plan, ...] = Field(default=(), description='Existing compiled locator Plans.')
sealed: StrictBool = Field(default=False, description='Logical finalization observed; caller owns provider cleanup.')
complete: StrictBool = Field(default=True, description='All evidence requested by policy was retained.')
limits: ArchiveLimits = Field(default_factory=ArchiveLimits, description='Limits governing this outcome.')
```

## Methods

### new

```python
@classmethod
def new(cls, id: str, limits: ArchiveLimits | None=None) -> Self:
```

Start a bounded outcome for an adapter-managed execution.

[Source: python/yosoi/surface.py:1021](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1021-L1027)

### with_source

```python
def with_source(self, source: ArchivedSource) -> Self:
```

Return a validated copy retaining one exact source.

Sealed, conflicting, corrupt or excessive input raises SurfaceError.
This immutable original remains unchanged when validation fails.

[Source: python/yosoi/surface.py:1029](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1029-L1037)

### validate_outcome

```python
def validate_outcome(self) -> None:
```

Check schema, record, source integrity, limits and compiled Plans in Rust.

[Source: python/yosoi/surface.py:1039](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1039-L1041)

### surface

```python
def surface(self, key: str, limits: Limits | None=None) -> Surface:
```

Restore immutable evidence without opening a browser or granting control.

[Source: python/yosoi/surface.py:1062](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1062-L1068)

### rerun

```python
async def rerun(self, policy: SurfacePolicy, count: int=1) -> tuple[Outcome, ...]:
```

Execute a supported recipe against fresh isolated live sessions.

Requires complete, sealed evidence and enabled archive policy. Rust
preflights supported operations before effects and resolves new targets
uniquely with live eligibility checks. Each run returns separate evidence.
Failed attempts remain in the selected policy output directory.

[Source: python/yosoi/surface.py:1070](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1070-L1084)

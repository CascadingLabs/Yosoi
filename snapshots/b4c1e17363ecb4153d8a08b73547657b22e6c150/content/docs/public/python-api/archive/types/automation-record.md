---
title: "AutomationRecord"
description: "yosoi.archive.AutomationRecord Python API reference."
order: 0
---

`yosoi.archive.AutomationRecord`

```python
class AutomationRecord(ImmutableModel):
```

Bounded observations and receipts validated by the Rust record contract.

This stores evidence, not executable Python objects or resumed Sessions.
Pydantic Contract instances are outside the portable Archive contract.

Attributes:
    version: Logical record schema version.
    id: Application-authored record identity.
    observations: Captured evidence with original Session, tab and epoch.
    operations: Ordered operation receipts with effect certainty preserved.
    flow_outcome: Optional original Flow declaration and observed outcome.
    context: Optional application-supplied provenance.

[Source: python/yosoi/archive.py:108](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/archive.py#L108-L144)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: Literal[1] = 1
id: StrictStr
observations: tuple[Observation, ...] = ()
operations: tuple[OperationReceipt, ...] = ()
flow_outcome: FlowOutcome | None = None
context: AutomationContext | None = None
```

## Methods

### from_flow

```python
@classmethod
def from_flow(cls, id: str, outcome: FlowOutcome) -> Self:
```

Retain a Flow's receipts, cleanup, failure capture and unique observations.

Rejected and unknown results remain intact. Inconsistent observations,
unsupported outcomes and excessive evidence raise ArchiveError.

[Source: python/yosoi/archive.py:136](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/archive.py#L136-L144)

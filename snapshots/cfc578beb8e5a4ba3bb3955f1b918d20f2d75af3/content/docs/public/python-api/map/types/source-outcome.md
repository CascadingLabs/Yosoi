---
title: "SourceOutcome"
description: "yosoi.map.SourceOutcome Python API reference."
order: 0
---

`yosoi.map.SourceOutcome`

```python
class SourceOutcome(ImmutableModel):
```

Execution facts for one selected discovery source.

Attributes:
    source: Discovery mechanism occupying the source slot.
    source_url: Reporting endpoint or page, or None when no URL applies.
    status: Terminal processing state, independent of overall exhaustion.

[Source: python/yosoi/map.py:421](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/map.py#L421-L432)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
source: DiscoverySource
source_url: str | None
status: SourceStatus
```

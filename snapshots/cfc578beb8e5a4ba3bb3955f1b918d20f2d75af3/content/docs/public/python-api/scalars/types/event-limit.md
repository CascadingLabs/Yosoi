---
title: "EventLimit"
description: "yosoi.scalars.EventLimit Python API reference."
order: 0
---

`yosoi.scalars.EventLimit`

```python
class EventLimit(ValidatedInteger):
```

Positive addressable u64 count of admitted browser capture events.

[Source: python/yosoi/scalars.py:280](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L280-L292)

## Base classes

[ValidatedInteger](/yosoi/python-api/scalars/types/validated-integer/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### default

```python
@classmethod
def default(cls) -> Self:
```

Return the browser event count selected by the Rust package default.

[Source: python/yosoi/scalars.py:286](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L286-L288)

### as_usize

```python
def as_usize(self) -> int:
```

Return the event count already checked for platform addressability.

[Source: python/yosoi/scalars.py:290](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L290-L292)

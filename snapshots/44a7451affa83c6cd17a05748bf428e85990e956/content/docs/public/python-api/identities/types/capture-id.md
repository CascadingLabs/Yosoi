---
title: "CaptureId"
description: "yosoi.identities.CaptureId Python API reference."
order: 0
---

`yosoi.identities.CaptureId`

```python
class CaptureId(ActivityId):
```

An activity identity designated as a capture by its Python type.

The type preserves capture-specific authoring vocabulary. Parsing a UUID
does not verify the existence or contents of a corresponding capture.

[Source: python/yosoi/identities.py:68](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/identities.py#L68-L93)

## Base classes

[ActivityId](/yosoi/python-api/identities/types/activity-id/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### random

```python
@classmethod
def random(cls) -> Self:
```

Generate a fresh capture identity without acquiring or archiving content.

[Source: python/yosoi/identities.py:87](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/identities.py#L87-L89)

### activity_id

```python
def activity_id(self) -> ActivityId:
```

Return the same UUID represented as the general activity type.

[Source: python/yosoi/identities.py:91](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/identities.py#L91-L93)

---
title: "ActivityId"
description: "yosoi.identities.ActivityId Python API reference."
order: 0
---

`yosoi.identities.ActivityId`

```python
class ActivityId(str):
```

Canonical random UUID v4 identity for one activity occurrence.

Parsing validates lowercase hyphenated RFC 4122 UUID v4 text in Rust; it
does not establish that an activity exists in an archive. As a string value,
the identity is immutable and can be serialized without native object state.

[Source: python/yosoi/identities.py:13](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/identities.py#L13-L65)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### random

```python
@classmethod
def random(cls) -> Self:
```

Generate a fresh UUID v4 in Rust without creating an archived activity.

[Source: python/yosoi/identities.py:33](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/identities.py#L33-L35)

### from_str

```python
@classmethod
def from_str(cls, value: str) -> Self:
```

Parse canonical text using the subclass constructor's validation.

Args:
    value: Lowercase hyphenated UUID v4 representation.

Returns:
    An immutable identity of the requested subclass.

Raises:
    RequestError: The text is invalid, noncanonical, or not RFC 4122 v4.

[Source: python/yosoi/identities.py:38](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/identities.py#L38-L50)

### as_bytes

```python
def as_bytes(self) -> bytes:
```

Return the 16 UUID bytes in network byte order as an owned value.

[Source: python/yosoi/identities.py:52](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/identities.py#L52-L54)

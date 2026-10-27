---
title: "DocumentMetadata"
description: "yosoi.request.DocumentMetadata Python API reference."
order: 0
---

`yosoi.request.DocumentMetadata`

```python
class DocumentMetadata(ImmutableModel):
```

Source document identity, representation, and byte accounting.

Attributes:
    id: Identity allocated to the document, not its source URL.
    profile: Declared representation profile used to interpret retained bytes.
    document_class: Native document capability class.
    byte_len: Number of bytes in the retained document payload.

[Source: python/yosoi/request.py:78](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L78-L91)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: str
profile: DocumentProfile
document_class: str
byte_len: int
```

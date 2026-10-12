---
title: "new"
description: "yosoi.search.new Python API reference."
order: 0
---

`yosoi.search.new`

```python
def new(query: str) -> SearchRequest:
```

Author a search request without provider I/O.

Args:
    query: Original nonblank query, limited to 512 UTF-8 bytes.

Returns:
    A request with a fresh activity identity and package-default behavior until
    bound.

Raises:
    pydantic.ValidationError: The query is not a string.
    SearchError: The query is blank or exceeds the Rust UTF-8 byte limit.

[Source: python/yosoi/search.py:751](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/search.py#L751-L765)

---
title: "response"
description: "yosoi.browser.response Python API reference."
order: 0
---

`yosoi.browser.response`

```python
def response(url: str, *, method: str | None=None, status: int | None=None, json_matches: Iterable[JsonMatch]=()) -> ResponseExpectation:
```

Declare a matching network-response expectation for Until.

Args:
    url: Exact full response URL.
    method: Optional HTTP method filter.
    status: Optional expected status from 100 through 599.
    json_matches: At most 32 pointer/value comparisons, copied into an immutable
        tuple.

Returns:
    ResponseExpectation; this does not send an HTTP request.

[Source: python/yosoi/browser.py:1772](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1772-L1796)

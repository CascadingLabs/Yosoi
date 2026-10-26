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

[Source: python/yosoi/browser.py:1772](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1772-L1796)

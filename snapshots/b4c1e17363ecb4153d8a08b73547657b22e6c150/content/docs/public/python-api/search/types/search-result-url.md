---
title: "SearchResultUrl"
description: "yosoi.search.SearchResultUrl Python API reference."
order: 0
---

`yosoi.search.SearchResultUrl`

```python
class SearchResultUrl(str):
```

An absolute HTTP(S) destination validated by Rust; no I/O occurs.

[Source: python/yosoi/search.py:23](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/search.py#L23-L74)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### parse

```python
@classmethod
def parse(cls, value: str) -> SearchResultUrl:
```

Validate an absolute HTTP(S) destination without fetching it.

Args:
    value: URL text without embedded credentials.

Returns:
    A validated string value; validation does not establish destination trust.

Raises:
    SearchError: The URL is invalid, uses an unsupported scheme, or embeds
        credentials.

[Source: python/yosoi/search.py:27](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/search.py#L27-L40)

### as_str

```python
def as_str(self) -> str:
```

Return validated URL text without performing I/O.

[Source: python/yosoi/search.py:53](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/search.py#L53-L55)

### as_request_target

```python
def as_request_target(self) -> str:
```

Return URL text for a later request without sending one.

[Source: python/yosoi/search.py:57](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/search.py#L57-L59)

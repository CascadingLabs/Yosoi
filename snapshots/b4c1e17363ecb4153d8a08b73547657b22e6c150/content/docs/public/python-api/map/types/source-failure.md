---
title: "SourceFailure"
description: "yosoi.map.SourceFailure Python API reference."
order: 0
---

`yosoi.map.SourceFailure`

```python
class SourceFailure(ImmutableModel):
```

Typed acquisition or parsing failure without raw response excerpts.

Attributes:
    kind: Classifies transport/status failures, malformed or incomplete content,
        redirect rejection/limits, retention limits, request deadlines, rate limits,
        or unexpected sitemap content.
    value: Unsuccessful HTTP status for http_status, otherwise None.

[Source: python/yosoi/map.py:275](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L275-L297)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['transport', 'http_status', 'parse', 'incomplete_document', 'redirect_rejected', 'redirect_limit', 'retention_limit', 'request_deadline', 'rate_limited', 'unexpected_sitemap_content']
value: int | None = None
```

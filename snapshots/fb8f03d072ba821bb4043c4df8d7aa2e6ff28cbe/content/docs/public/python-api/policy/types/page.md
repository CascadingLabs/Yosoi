---
title: "Page"
description: "yosoi.policy.Page Python API reference."
order: 0
---

`yosoi.policy.Page`

```python
class Page(Model):
```

Ordered bounded acquisitions for one page request.

Attributes:
    acquisitions: Authored acquisitions in execution/outcome order; at most three
        declarations are accepted.

[Source: python/yosoi/policy.py:306](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L306-L316)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisitions: Annotated[list[Acquisition], Field(max_length=3)] = _field('page', 'acquisitions')
```

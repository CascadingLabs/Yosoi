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

[Source: python/yosoi/policy.py:306](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L306-L316)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisitions: Annotated[list[Acquisition], Field(max_length=3)] = _field('page', 'acquisitions')
```

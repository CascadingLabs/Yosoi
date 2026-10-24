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

[Source: python/yosoi/policy.py:294](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L294-L304)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisitions: Annotated[list[Acquisition], Field(max_length=3)] = _field('page', 'acquisitions')
```

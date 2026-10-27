---
title: "Failure"
description: "yosoi.outcomes.Failure Python API reference."
order: 0
---

`yosoi.outcomes.Failure`

```python
class Failure(ImmutableModel):
```

Typed terminal locator failure without hostile document excerpts.

Attributes:
    kind: invalid_plan, parse_failed, unsupported_combination, limit_exhausted, or
        invalid_resource_policy determines which details apply.
    code: Bounded structural parser or plan identifier, when applicable.
    document: Unsupported document class for unsupported_combination.
    limit: Resource whose execution or policy boundary was rejected.
    maximum: Configured maximum in units of the named resource, when applicable.
    observed: Recorded or attempted consumption in the same units, when applicable.

[Source: python/yosoi/outcomes.py:917](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L917-L945)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['invalid_plan', 'parse_failed', 'unsupported_combination', 'limit_exhausted', 'invalid_resource_policy']
code: str | None = Field(default=None, exclude_if=lambda value: value is None)
document: DocumentClassName | None = Field(default=None, exclude_if=lambda value: value is None)
limit: ResourceLimit | None = Field(default=None, exclude_if=lambda value: value is None)
maximum: U64 | None = Field(default=None, exclude_if=lambda value: value is None)
observed: U64 | None = Field(default=None, exclude_if=lambda value: value is None)
```

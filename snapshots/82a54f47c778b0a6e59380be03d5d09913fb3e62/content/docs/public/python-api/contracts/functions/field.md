---
title: "Field"
description: "yosoi.contracts.Field Python API reference."
order: 0
---

`yosoi.contracts.Field`

```python
def Field(description: str, *, id: str | FieldId | None=None, locator: Locator | Query | None=None, default: Any=PydanticUndefined, **kwargs: Any) -> Any:
```

Describe a Contract field using a genuine Pydantic FieldInfo.

A bare query uses text projection. Defaults affect model authoring, while
extraction cardinality and missing-value behavior follow the Rust schema.

[Source: python/yosoi/contracts.py:110](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L110-L132)

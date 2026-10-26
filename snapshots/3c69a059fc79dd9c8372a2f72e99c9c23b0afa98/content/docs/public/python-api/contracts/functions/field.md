---
title: "Field"
description: "yosoi.contracts.Field Python API reference."
order: 0
---

`yosoi.contracts.Field`

```python
def Field(description: str | None=None, *, id: str | FieldId | None=None, locator: Locator | Query | None=None, default: Any=PydanticUndefined, **kwargs: Any) -> Any:
```

Describe a Contract field using a genuine Pydantic FieldInfo.

A bare query uses text projection. Pydantic constraints, aliases, defaults, and
other FieldInfo options are forwarded. Only the locator and field ID participate in
native candidate extraction; Pydantic validates each raw projected value.

[Source: python/yosoi/contracts.py:134](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L134-L157)

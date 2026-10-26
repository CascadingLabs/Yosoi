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

[Source: python/yosoi/contracts.py:134](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/contracts.py#L134-L157)

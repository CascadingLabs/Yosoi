---
title: "ValidatedInteger"
description: "yosoi.scalars.ValidatedInteger Python API reference."
order: 0
---

`yosoi.scalars.ValidatedInteger`

```python
class ValidatedInteger(int):
```

Integer scalar with the width and constructor rules of its Rust type.

[Source: python/yosoi/scalars.py:102](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/scalars.py#L102-L167)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### try_new

```python
@classmethod
def try_new(cls, value: int) -> Self:
```

Validate an integer using the domain-specific subclass constructor.

Args:
    value: Authored integer in the selected scalar's units.

Returns:
    An immutable scalar checked by its Rust constructor.

Raises:
    YosoiError: The selected domain rejects the width or value.

[Source: python/yosoi/scalars.py:123](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/scalars.py#L123-L135)

### get

```python
def get(self) -> int:
```

Return the retained numeric value without converting its units.

[Source: python/yosoi/scalars.py:137](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/scalars.py#L137-L139)

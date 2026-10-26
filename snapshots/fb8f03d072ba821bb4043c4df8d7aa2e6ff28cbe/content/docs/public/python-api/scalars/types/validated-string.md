---
title: "ValidatedString"
description: "yosoi.scalars.ValidatedString Python API reference."
order: 0
---

`yosoi.scalars.ValidatedString`

```python
class ValidatedString(str):
```

String scalar constructed and checked by its Rust SDK type.

[Source: python/yosoi/scalars.py:34](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L34-L99)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### try_new

```python
@classmethod
def try_new(cls, value: str) -> Self:
```

Validate text using the domain-specific subclass constructor.

Args:
    value: Authored string to validate in Rust.

Returns:
    An immutable instance of the selected string scalar subclass.

Raises:
    YosoiError: The selected domain rejects the supplied string.

[Source: python/yosoi/scalars.py:55](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L55-L67)

### as_str

```python
def as_str(self) -> str:
```

Return the validated retained spelling as an ordinary Python string.

[Source: python/yosoi/scalars.py:69](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L69-L71)

---
title: "Plan"
description: "yosoi.locators.Plan Python API reference."
order: 0
---

`yosoi.locators.Plan`

```python
class Plan(ImmutableModel):
```

Compiled immutable outputs and repeated-region declarations.

Attributes:
    outputs: Ordered named output declarations. Native compilation checks IDs,
        projection compatibility, and region structure without acquiring documents.

[Source: python/yosoi/locators.py:544](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L544-L643)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
outputs: tuple[Output, ...]
```

## Methods

### model_post_init

```python
def model_post_init(self, context: object) -> None:
```

Retain an existing native plan or compile declared outputs through Rust.

[Source: python/yosoi/locators.py:555](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L555-L563)

### from_compiled

```python
@classmethod
def from_compiled(cls, value: str | Mapping[str, Any]) -> Self:
```

Import a portable Rust Plan; Rust validates all compiled invariants.

[Source: python/yosoi/locators.py:566](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L566-L606)

### compiled

```python
def compiled(self) -> dict[str, object]:
```

Inspect the portable plan compiled by Rust.

[Source: python/yosoi/locators.py:608](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L608-L610)

### model_copy

```python
def model_copy(self, *, update: Mapping[str, Any] | None=None, deep: bool=False) -> Self:
```

Copy immutable authoring intent and revalidate changed inputs.

Args:
    update: Optional authoring replacements to validate in Rust.
    deep: Reconstruct the declaration when True.

Returns:
    A validated copy. Unchanged shallow copies retain compiled ownership.

Raises:
    LocatorError: Changed declarations fail native semantic validation.
    pydantic.ValidationError: Updated authoring fields are invalid.

[Source: python/yosoi/locators.py:612](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L612-L630)

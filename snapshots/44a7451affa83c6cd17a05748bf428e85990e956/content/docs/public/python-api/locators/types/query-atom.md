---
title: "QueryAtom"
description: "yosoi.locators.QueryAtom Python API reference."
order: 0
---

`yosoi.locators.QueryAtom`

```python
class QueryAtom(ImmutableModel):
```

Closed portable query meaning, separate from Python authoring syntax.

Attributes:
    kind: CSS/XPath, JSON, accessibility, or decoded-text operation label.
    value: Authored expression text, or a typed accessibility-state operand.

[Source: python/yosoi/locators.py:96](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/locators.py#L96-L126)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['css', 'x_path', 'tree_text_contains', 'json_pointer', 'json_path', 'accessibility_role', 'accessible_name', 'accessibility_text', 'accessibility_state', 'text_literal', 'text_regex']
value: str | AccessibilityStateAtom
```

## Methods

### expression

```python
@property
def expression(self) -> str:
```

Return expression text, or the state name for a boolean state query.

[Source: python/yosoi/locators.py:120](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/locators.py#L120-L126)

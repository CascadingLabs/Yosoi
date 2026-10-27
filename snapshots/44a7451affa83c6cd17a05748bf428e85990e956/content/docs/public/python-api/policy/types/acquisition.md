---
title: "Acquisition"
description: "yosoi.policy.Acquisition Python API reference."
order: 0
---

`yosoi.policy.Acquisition`

```python
class Acquisition(Model):
```

Authored acquisition mechanism with explicit document selection.

Attributes:
    kind: direct_http or browser selects the acquisition adapter family.
    mode: Required headless/headful selection for browser, absent for direct HTTP.
    documents: Current defaults or exact authored output representations. Direct
        HTTP supports only a response document.

[Source: python/yosoi/policy.py:219](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L219-L303)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['direct_http', 'browser'] = 'direct_http'
mode: BrowserMode | None = Field(default=None, exclude_if=lambda value: value is None)
documents: DocumentSelection = Field(default_factory=DocumentSelection)
```

## Methods

### direct_http

```python
@classmethod
def direct_http(cls) -> Self:
```

Return Direct HTTP authoring with current document-selection defaults.

[Source: python/yosoi/policy.py:250](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L250-L252)

### browser

```python
@classmethod
def browser(cls, mode: Literal['headless', 'headful']='headless') -> Self:
```

Declare browser acquisition without launching a browser.

Args:
    mode: Headless or headful selection, defaulting to headless.

Returns:
    Browser authoring with current document-selection defaults.

[Source: python/yosoi/policy.py:255](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L255-L264)

### with_documents

```python
def with_documents(self, documents: list[str] | tuple[str, ...]) -> Self:
```

Return a new acquisition with exact authored document outputs.

Args:
    documents: Supported representations, including an explicit empty selection.

Returns:
    Revalidated acquisition without changing this declaration.

Raises:
    PolicyError: The adapter kind or selected document outputs are unsupported.

[Source: python/yosoi/policy.py:266](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L266-L284)

### exact_documents

```python
@property
def exact_documents(self) -> tuple[str, ...] | None:
```

Return exact authored outputs, or None for a Current selection.

[Source: python/yosoi/policy.py:287](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L287-L294)

### selection_kind

```python
@property
def selection_kind(self) -> Literal['current', 'exact']:
```

Return whether outputs were selected by Current defaults or explicitly.

[Source: python/yosoi/policy.py:297](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L297-L303)

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

[Source: python/yosoi/policy.py:207](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L207-L291)

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

[Source: python/yosoi/policy.py:238](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L238-L240)

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

[Source: python/yosoi/policy.py:243](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L243-L252)

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

[Source: python/yosoi/policy.py:254](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L254-L272)

### exact_documents

```python
@property
def exact_documents(self) -> tuple[str, ...] | None:
```

Return exact authored outputs, or None for a Current selection.

[Source: python/yosoi/policy.py:275](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L275-L282)

### selection_kind

```python
@property
def selection_kind(self) -> Literal['current', 'exact']:
```

Return whether outputs were selected by Current defaults or explicitly.

[Source: python/yosoi/policy.py:285](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L285-L291)

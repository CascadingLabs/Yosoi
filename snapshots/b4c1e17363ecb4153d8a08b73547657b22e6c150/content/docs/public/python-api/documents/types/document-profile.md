---
title: "DocumentProfile"
description: "yosoi.documents.DocumentProfile Python API reference."
order: 0
---

`yosoi.documents.DocumentProfile`

```python
class DocumentProfile(ImmutableModel):
```

Validated representation and schema for retained payload bytes.

Attributes:
    representation: source, rendered_dom, or accessibility_tree selects
        capabilities.
    source_format: Owned payload syntax: html, xml, json, or text.
    schema_profile: Exact parser/schema profile, serialized under the field name
        schema.
    epoch: Positive generation for rendered DOM and accessibility snapshots; source
        profiles omit it.

[Source: python/yosoi/documents.py:34](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L34-L144)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
representation: Literal['source', 'rendered_dom', 'accessibility_tree']
source_format: SourceFormat
schema_profile: Literal['html5', 'xml10', 'json_rfc8259', 'utf8_text', 'yosoi_rendered_dom_v1', 'yosoi_accessibility_tree_v1'] = Field(alias='schema')
epoch: DocumentEpoch | None = None
```

## Methods

### source_html

```python
@classmethod
def source_html(cls) -> Self:
```

Return a source HTML5 profile without a snapshot epoch.

[Source: python/yosoi/documents.py:70](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L70-L74)

### source_xml

```python
@classmethod
def source_xml(cls) -> Self:
```

Return a source XML 1.0 profile without a snapshot epoch.

[Source: python/yosoi/documents.py:77](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L77-L79)

### source_json

```python
@classmethod
def source_json(cls) -> Self:
```

Return a source RFC 8259 JSON profile without a snapshot epoch.

[Source: python/yosoi/documents.py:82](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L82-L88)

### source_text

```python
@classmethod
def source_text(cls) -> Self:
```

Return a source UTF-8 text profile without a snapshot epoch.

[Source: python/yosoi/documents.py:91](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L91-L95)

### rendered_dom

```python
@classmethod
def rendered_dom(cls, epoch: int | DocumentEpoch) -> Self:
```

Declare retained rendered DOM snapshot interpretation.

Args:
    epoch: Positive immutable browser snapshot generation.

Returns:
    A validated profile without capturing a live browser.

Raises:
    pydantic.ValidationError: Epoch or authoring fields are invalid.
    DocumentError: Native profile or document validation rejects the inputs.

[Source: python/yosoi/documents.py:98](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L98-L116)

### accessibility_tree

```python
@classmethod
def accessibility_tree(cls, epoch: int | DocumentEpoch) -> Self:
```

Declare retained accessibility snapshot interpretation.

Args:
    epoch: Positive immutable browser snapshot generation.

Returns:
    A validated profile without capturing a live browser.

Raises:
    pydantic.ValidationError: Epoch or authoring fields are invalid.
    DocumentError: Native profile or document validation rejects the inputs.

[Source: python/yosoi/documents.py:119](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L119-L137)

### document_class

```python
@property
def document_class(self) -> DocumentClass:
```

Return the native capability class for this validated profile.

[Source: python/yosoi/documents.py:140](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/documents.py#L140-L144)

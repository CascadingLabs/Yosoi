---
title: "Document"
description: "yosoi.documents.Document Python API reference."
order: 0
---

`yosoi.documents.Document`

```python
class Document(ImmutableModel):
```

Immutable document bytes with retained native parse ownership.

Attributes:
    id: Validated document identity, independent of any source URL.
    profile: Representation and schema interpretation of the retained bytes.
    data: Exact owned bytes; text inputs are UTF-8 encoded. Model dumps omit payload
        data by default.

[Source: python/yosoi/documents.py:155](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L155-L418)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: DocumentId
profile: DocumentProfile
data: bytes = Field(repr=False, exclude=True)
```

## Methods

### model_post_init

```python
def model_post_init(self, context: object) -> None:
```

Create or validate native ownership of these exact document inputs.

[Source: python/yosoi/documents.py:170](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L170-L178)

### html

```python
@classmethod
def html(cls, id: str, content: str | bytes) -> Self:
```

Retain source bytes using the HTML5 interpretation.

Args:
    id: Authored document identity, independent of any acquisition URL.
    content: Exact bytes, or text to encode as UTF-8.

Returns:
    A document owning its payload without external acquisition.

Raises:
    pydantic.ValidationError: Identity or authoring fields are invalid.
    DocumentError: Native construction rejects the supplied inputs.

[Source: python/yosoi/documents.py:192](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L192-L206)

### xml

```python
@classmethod
def xml(cls, id: str, content: str | bytes) -> Self:
```

Retain source bytes using the XML 1.0 interpretation.

Args:
    id: Authored document identity, independent of any acquisition URL.
    content: Exact bytes, or text to encode as UTF-8.

Returns:
    A document owning its payload without external acquisition.

Raises:
    pydantic.ValidationError: Identity or authoring fields are invalid.
    DocumentError: Native construction rejects the supplied inputs.

[Source: python/yosoi/documents.py:209](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L209-L223)

### from_json

```python
@classmethod
def from_json(cls, id: str, content: str | bytes) -> Self:
```

Retain source bytes using the RFC 8259 JSON interpretation.

Args:
    id: Authored document identity, independent of any acquisition URL.
    content: Exact bytes, or text to encode as UTF-8.

Returns:
    A document owning its payload without external acquisition.

Raises:
    pydantic.ValidationError: Identity or authoring fields are invalid.
    DocumentError: Native construction rejects the supplied inputs.

[Source: python/yosoi/documents.py:226](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L226-L240)

### text

```python
@classmethod
def text(cls, id: str, content: str | bytes) -> Self:
```

Retain source bytes using the UTF-8 text interpretation.

Args:
    id: Authored document identity, independent of any acquisition URL.
    content: Exact bytes, or text to encode as UTF-8.

Returns:
    A document owning its payload without external acquisition.

Raises:
    pydantic.ValidationError: Identity or authoring fields are invalid.
    DocumentError: Native construction rejects the supplied inputs.

[Source: python/yosoi/documents.py:243](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L243-L257)

### from_profile

```python
@classmethod
def from_profile(cls, id: str, profile: DocumentProfile, content: str | bytes) -> Self:
```

Retain content using an explicit interpretation profile.

Args:
    id: Authored document identity.
    profile: Validated representation, syntax, schema, and epoch declaration.
    content: Exact bytes, or text to encode as UTF-8.

Returns:
    Immutable payload ownership without external acquisition.

Raises:
    pydantic.ValidationError: Identity or authoring fields are invalid.
    DocumentError: Native construction rejects the supplied inputs.

[Source: python/yosoi/documents.py:260](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L260-L277)

### rendered_dom

```python
@classmethod
def rendered_dom(cls, id: str, epoch: int | DocumentEpoch, content: str | bytes) -> Self:
```

Declare retained rendered DOM snapshot interpretation.

Args:
    id: Authored document identity.
    epoch: Positive immutable browser snapshot generation.
    content: JSON snapshot bytes or text in the supported version-1 schema.

Returns:
    A retained snapshot document without querying a live browser.

Raises:
    pydantic.ValidationError: Epoch or authoring fields are invalid.
    DocumentError: Native profile or document validation rejects the inputs.

[Source: python/yosoi/documents.py:280](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L280-L305)

### accessibility_tree

```python
@classmethod
def accessibility_tree(cls, id: str, epoch: int | DocumentEpoch, content: str | bytes) -> Self:
```

Declare retained accessibility snapshot interpretation.

Args:
    id: Authored document identity.
    epoch: Positive immutable browser snapshot generation.
    content: JSON snapshot bytes or text in the supported version-1 schema.

Returns:
    A retained snapshot document without querying a live browser.

Raises:
    pydantic.ValidationError: Epoch or authoring fields are invalid.
    DocumentError: Native profile or document validation rejects the inputs.

[Source: python/yosoi/documents.py:308](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L308-L333)

### byte_len

```python
@property
def byte_len(self) -> int:
```

Return retained payload bytes, not decoded character count.

[Source: python/yosoi/documents.py:336](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L336-L338)

### document_class

```python
@property
def document_class(self) -> DocumentClass:
```

Return the native capability class of the retained payload.

[Source: python/yosoi/documents.py:341](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L341-L343)

### bind

```python
def bind(self, policy: Policy) -> BoundDocument:
```

Snapshot a complete policy without acquiring new data.

Args:
    policy: Complete declaration to serialize now.

Returns:
    A document binding unaffected by later caller-policy edits.

[Source: python/yosoi/documents.py:345](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L345-L354)

### locate

```python
def locate(self, plan: Plan) -> LocateOutcome:
```

Execute a bounded locator plan against retained payload bytes.

Args:
    plan: Authored outputs, projections, and repeated regions.

Returns:
    Typed matches, complete absence, indeterminate evidence, or failure.
    No network acquisition occurs; empty convenience collections alone do
    not establish complete absence.

[Source: python/yosoi/documents.py:356](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L356-L367)

### parse

```python
def parse(self) -> ParsedDocument:
```

Create a reusable native parse using default resource policy.

Returns:
    A parse owner to close explicitly or use as a context manager.

Raises:
    ParseError: Parsing or resource checks reject the retained payload.

[Source: python/yosoi/documents.py:369](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L369-L378)

### model_copy

```python
def model_copy(self, *, update: Mapping[str, Any] | None=None, deep: bool=False) -> Self:
```

Copy authoring values while preserving valid native ownership.

Args:
    update: Optional replacement fields to revalidate.
    deep: Reconstruct through the public constructor when True.

Returns:
    A document copy. Unchanged shallow copies retain the native handle;
    updated or deep copies are reconstructed and revalidated.

Raises:
    pydantic.ValidationError: Updated authoring fields are invalid.
    DocumentError: Native reconstruction rejects the supplied inputs.

[Source: python/yosoi/documents.py:380](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/documents.py#L380-L400)

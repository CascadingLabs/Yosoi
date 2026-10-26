---
title: "QuerySpec"
description: "yosoi.locators.QuerySpec Python API reference."
order: 0
---

`yosoi.locators.QuerySpec`

```python
class QuerySpec(ImmutableModel):
```

Portable Rust query semantics with validated result shape.

Attributes:
    atom: Closed query operation and expression or state operand.
    result_shape: tree_nodes, json_values, accessibility_nodes, or text_ranges
        retains capability distinctions.
    namespace_bindings: Explicit query-local XML namespace mappings; absent bindings
        are not inferred from document prefixes.

[Source: python/yosoi/locators.py:141](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L141-L221)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
atom: QueryAtom
result_shape: QueryResultShape
namespace_bindings: tuple[NamespaceBinding, ...] = Field(default=(), exclude_if=lambda value: not value)
```

## Methods

### new

```python
@classmethod
def new(cls, atom: QueryAtom, result_shape: QueryResultShape) -> Self:
```

Validate a portable query operation and result shape through Rust.

Args:
    atom: Closed query operation and authored operand.
    result_shape: Capability shape expected for the operation.

Returns:
    A validated specification without locating any document evidence.

Raises:
    LocatorError: Rust query structure or result-shape compatibility is invalid.

[Source: python/yosoi/locators.py:164](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L164-L177)

### query_bytes

```python
@property
def query_bytes(self) -> int:
```

Return Rust-accounted query input bytes, including namespace metadata.

[Source: python/yosoi/locators.py:180](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L180-L184)

### with_namespace

```python
def with_namespace(self, prefix: str, uri: str) -> Self:
```

Attach one explicit XML namespace prefix without searching documents.

Args:
    prefix: Valid authored query prefix, unique within this declaration.
    uri: Nonblank namespace URI for expanded-name matching.

Returns:
    A new validated query retaining the original declaration unchanged.

Raises:
    LocatorError: Prefix, URI, duplicate binding, or query kind is unsupported.

[Source: python/yosoi/locators.py:186](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L186-L201)

### with_default_namespace

```python
def with_default_namespace(self, uri: str) -> Self:
```

Attach an explicit default XML namespace without inferring source prefixes.

Args:
    uri: Nonblank namespace URI for supported default-namespace query semantics.

Returns:
    A new validated query with an explicit empty-prefix binding.

Raises:
    LocatorError: Namespace metadata or query-kind support is invalid.

[Source: python/yosoi/locators.py:203](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L203-L217)

### to_query

```python
def to_query(self) -> Query:
```

Reconstruct validated Python authoring intent from portable semantics.

[Source: python/yosoi/locators.py:219](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L219-L221)

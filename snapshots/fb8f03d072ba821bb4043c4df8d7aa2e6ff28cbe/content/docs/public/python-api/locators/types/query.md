---
title: "Query"
description: "yosoi.locators.Query Python API reference."
order: 0
---

`yosoi.locators.Query`

```python
class Query(ImmutableModel):
```

Immutable locator intent compiled and checked by the Rust SDK.

Attributes:
    kind: Python authoring operation; compiled wire tags can differ.
    expression: Authored query text retained without acquiring or searching
        documents.
    namespaces: Explicit XML bindings, with unique prefixes.
    state: Boolean operand for an accessibility-state query, otherwise None.
    shape: Rust-resolved result capability; it does not prove a document supports
        the query.
    within: Optional single repeated-region scope. Nested region declarations are
        unsupported.

[Source: python/yosoi/locators.py:224](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L224-L471)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: QueryKind
expression: str
namespaces: tuple[NamespaceBinding, ...] = ()
state: bool | None = None
shape: QueryResultShape | None = None
within: Region | None = None
```

## Methods

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

[Source: python/yosoi/locators.py:268](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L268-L286)

### compiled

```python
def compiled(self) -> QuerySpec:
```

Return portable semantics compiled by Rust without executing a locator.

[Source: python/yosoi/locators.py:288](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L288-L294)

### atom

```python
@property
def atom(self) -> QueryAtom:
```

Return the Rust-compiled closed query operation and operand.

[Source: python/yosoi/locators.py:297](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L297-L299)

### result_shape

```python
@property
def result_shape(self) -> QueryResultShape:
```

Return the Rust-resolved result capability without locating a document.

[Source: python/yosoi/locators.py:302](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L302-L304)

### namespace_bindings

```python
@property
def namespace_bindings(self) -> tuple[NamespaceBinding, ...]:
```

Return explicit compiled XML bindings in their retained order.

[Source: python/yosoi/locators.py:307](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L307-L309)

### query_bytes

```python
@property
def query_bytes(self) -> int:
```

Return query input bytes accounted by the compiled Rust specification.

[Source: python/yosoi/locators.py:312](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L312-L314)

### from_compiled

```python
@classmethod
def from_compiled(cls, spec: QuerySpec | Mapping[str, Any]) -> Self:
```

Reconstruct authoring intent from validated portable query semantics.

Args:
    spec: QuerySpec or mapping containing a Rust-compatible atom and shape.

Returns:
    A query retaining compiled meaning without acquiring documents.

Raises:
    LocatorError: Native query semantics cannot be represented.
    pydantic.ValidationError: The portable input structure is invalid.

[Source: python/yosoi/locators.py:317](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L317-L350)

### with_namespace

```python
def with_namespace(self, prefix: str, uri: str) -> Query:
```

Attach one explicit XML namespace prefix without searching documents.

Args:
    prefix: Valid authored query prefix, unique within this declaration.
    uri: Nonblank namespace URI for expanded-name matching.

Returns:
    A new validated query retaining the original declaration unchanged.

Raises:
    LocatorError: Prefix, URI, duplicate binding, or query kind is unsupported.

[Source: python/yosoi/locators.py:352](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L352-L369)

### with_default_namespace

```python
def with_default_namespace(self, uri: str) -> Query:
```

Attach an explicit default XML namespace without inferring source prefixes.

Args:
    uri: Nonblank namespace URI for supported default-namespace query semantics.

Returns:
    A new validated query with an explicit empty-prefix binding.

Raises:
    LocatorError: Namespace metadata or query-kind support is invalid.

[Source: python/yosoi/locators.py:371](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L371-L385)

### each_as_region

```python
def each_as_region(self, id: str) -> Region:
```

Declare this query as one repeated-region root.

Args:
    id: Authored lineage identity used to group scoped output findings.

Returns:
    A region declaration without evaluating matches.

Raises:
    LocatorError: The region identity or nested-region structure is invalid.

[Source: python/yosoi/locators.py:387](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L387-L399)

### text

```python
def text(self) -> Locator:
```

Request projection of supported text evidence.

Returns:
    A locator declaration without executing the query or acquiring evidence.

Raises:
    LocatorError: The query's capability shape cannot support this projection.

[Source: python/yosoi/locators.py:401](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L401-L410)

### attribute

```python
def attribute(self, name: str) -> Locator:
```

Request named attribute values from a compatible query result.

Args:
    name: Attribute name to project from matched nodes.

Returns:
    A locator declaration; no document evidence is acquired.

Raises:
    LocatorError: Attribute metadata or projection compatibility is invalid.

[Source: python/yosoi/locators.py:412](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L412-L424)

### value

```python
def value(self) -> Locator:
```

Request projection of native JSON values.

Returns:
    A locator declaration without executing the query or acquiring evidence.

Raises:
    LocatorError: The query's capability shape cannot support this projection.

[Source: python/yosoi/locators.py:426](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L426-L435)

### node

```python
def node(self) -> Locator:
```

Request projection of document-bound node references.

Returns:
    A locator declaration without executing the query or acquiring evidence.

Raises:
    LocatorError: The query's capability shape cannot support this projection.

[Source: python/yosoi/locators.py:437](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L437-L446)

### name

```python
def name(self) -> Locator:
```

Request projection of accessible node names.

Returns:
    A locator declaration without executing the query or acquiring evidence.

Raises:
    LocatorError: The query's capability shape cannot support this projection.

[Source: python/yosoi/locators.py:448](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L448-L457)

### captures

```python
def captures(self, *names: str) -> Locator:
```

Request selected named regex captures alongside matched text.

Args:
    names: Capture names to retain from a supported text-regex query.

Returns:
    A projection declaration without executing the query.

Raises:
    LocatorError: Capture names or query/projection compatibility is invalid.

[Source: python/yosoi/locators.py:459](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L459-L471)

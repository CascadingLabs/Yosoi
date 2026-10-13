---
title: "ArchivedContractOutcome"
description: "yosoi.runtime_contracts.ArchivedContractOutcome Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractOutcome`

```python
class ArchivedContractOutcome:
```

Inspect a portable Contract outcome without a live Rust handle.

Parsing verifies the archive structure; it does not re-execute extraction or prove
business success. The original JSON is retained unchanged.

Attributes:
    view: Immutable status-tagged DTO parsed from the supplied archive JSON.

[Source: python/yosoi/runtime_contracts.py:437](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L437-L529)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, value: str) -> None:
```

Parse a portable archive and seal its typed view.

Args:
    value: Archive JSON emitted by Rust or a retained portable artifact.

Raises:
    ValueError: JSON is malformed or does not match an archive outcome variant.

[Source: python/yosoi/runtime_contracts.py:449](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L449-L465)

### status

```python
@property
def status(self) -> str:
```

Return the wire status; it does not alone prove business success.

[Source: python/yosoi/runtime_contracts.py:474](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L474-L476)

### document_id

```python
@property
def document_id(self) -> str | None:
```

Return the source document identity when this status carries one.

[Source: python/yosoi/runtime_contracts.py:479](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L479-L481)

### completeness

```python
@property
def completeness(self) -> IncompleteEvidence | None:
```

Return incomplete-evidence details for an indeterminate result, else None.

[Source: python/yosoi/runtime_contracts.py:484](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L484-L486)

### reason_code

```python
@property
def reason_code(self) -> str | None:
```

Return the indeterminate reason code, or None for other statuses.

[Source: python/yosoi/runtime_contracts.py:489](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L489-L491)

### failure

```python
@property
def failure(self) -> Failure | ArchivedExtractionFailure | ArchivedValidationFailure | None:
```

Return the typed phase failure, or None when this status has no failure.

[Source: python/yosoi/runtime_contracts.py:494](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L494-L498)

### records

```python
@property
def records(self) -> tuple[ArchivedValidatedContractRecord, ...]:
```

Return accepted records for evaluated results, otherwise an empty tuple.

[Source: python/yosoi/runtime_contracts.py:501](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L501-L503)

### issues

```python
@property
def issues(self) -> tuple[ArchivedContractRecordIssue, ...]:
```

Return evaluated candidate issues, or an empty tuple otherwise.

[Source: python/yosoi/runtime_contracts.py:506](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L506-L508)

### extraction_diagnostics

```python
@property
def extraction_diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
```

Return evaluated extraction diagnostics, otherwise an empty tuple.

[Source: python/yosoi/runtime_contracts.py:511](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L511-L517)

### to_json

```python
def to_json(self) -> str:
```

Return the original archive JSON unchanged.

[Source: python/yosoi/runtime_contracts.py:519](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L519-L521)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Decode the original wire into a new dictionary.

[Source: python/yosoi/runtime_contracts.py:523](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L523-L525)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return the original archive JSON unchanged.

[Source: python/yosoi/runtime_contracts.py:527](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L527-L529)

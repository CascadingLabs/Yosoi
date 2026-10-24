---
title: "RuntimeContract"
description: "yosoi.runtime_contracts.RuntimeContract Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeContract`

```python
class RuntimeContract(NativeAuthoringModel):
```

Author a Contract schema for extraction and validation in Rust.

The schema defines grouping, fields, cardinalities, and value types. Unsupported
conversions remain explicit validation issues rather than inferred Python
conversions.

Attributes:
    contract_schema: Public schema validated when the native Contract is
        constructed.

[Source: python/yosoi/runtime_contracts.py:1047](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L1047-L1129)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
contract_schema: ContractSchema
```

## Methods

### model_post_init

```python
def model_post_init(self, context: object) -> None:
```

Construct the native Contract from the validated Pydantic schema.

Args:
    context: Pydantic initialization context; unused by this bridge.

Raises:
    ContractError: Rust rejects the authored schema.

[Source: python/yosoi/runtime_contracts.py:1062](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L1062-L1071)

### new

```python
@classmethod
def new(cls, schema: ContractSchema) -> RuntimeContract:
```

Construct a runtime Contract using the supplied public schema.

Args:
    schema: Contract identity, grouping, fields, and validation declarations.

Returns:
    Contract whose native handle has accepted the schema.

Raises:
    ContractError: Rust rejects the authored schema.

[Source: python/yosoi/runtime_contracts.py:1074](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L1074-L1086)

### identity

```python
def identity(self) -> ContractIdentity:
```

Return the Rust-generated identity of this authored Contract schema.

[Source: python/yosoi/runtime_contracts.py:1088](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L1088-L1090)

### extract

```python
def extract(self, located: LocateOutcome, *, limits: ExtractionLimits | None=None) -> RuntimeExtracted:
```

Group located findings into unvalidated runtime candidates.

Args:
    located: Locator result carrying findings, provenance, and completeness.
    limits: Optional extraction budgets; None uses Rust defaults.

Returns:
    Candidates, no-match, indeterminate evidence, locator failure, or a typed
    extraction rejection. Call validate() to obtain accepted field values.

[Source: python/yosoi/runtime_contracts.py:1092](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L1092-L1112)

### locate

```python
def locate(self, document: Document | BoundDocument | ParsedDocument, plan: Plan) -> RuntimeExtracted:
```

Locate document evidence and extract candidates using this Contract.

Args:
    document: Offline, parsed, or bound document providing locator evaluation.
    plan: Discovery plan used to locate findings before extraction.

Returns:
    Unvalidated extraction result retaining locator completeness or failure.
    Validation is a separate operation on the returned result.

[Source: python/yosoi/runtime_contracts.py:1114](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L1114-L1129)

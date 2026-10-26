---
title: "Policy"
description: "yosoi.policy.Policy Python API reference."
order: 0
---

`yosoi.policy.Policy`

```python
class Policy(Model):
```

Editable complete declaration with Rust-owned defaults and validation.

Attributes:
    network: Opt-in IP family, local source binding, and upstream proxy.
    browser: Browser engine and optional launch/profile configuration.
    default_action_timeout_ms: Positive fallback action duration in milliseconds;
        explicit action/Flow budgets can override it.
    flow: Independent failure/cancellation continuation defaults.
    page: Ordered acquisition declarations and output selections.
    request: Acquisition timing, evidence limits, and redirect behavior.
    documents: Retained-payload parsing limits.
    locators: Query/traversal/finding resource limits.
    tuning: Supported package tuning declaration.
    map: Bounded site discovery scope and budgets.
    search: Ordered search provider selection and shared limits. Later edits are
        rechecked by check, to_json, or snapshot.

[Source: python/yosoi/policy.py:1265](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1265-L1342)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
model_config = ConfigDict(hide_input_in_errors=True)
network: Network = Field(default_factory=Network, exclude_if=_network_is_default)
browser: BrowserConfig = Field(default_factory=BrowserConfig)
default_action_timeout_ms: PositiveU64 = 10000
flow: FlowPolicy = Field(default_factory=FlowPolicy)
page: Page = _field('page')
request: Request = _field('request')
documents: Documents = _field('documents')
locators: Locators = _field('locators')
tuning: Tuning = Field(default_factory=Tuning)
map: Map = _field('map')
search: Search = _field('search')
```

## Methods

### check

```python
def check(self) -> None:
```

Validate this declaration in Rust, including later edits.

[Source: python/yosoi/policy.py:1313](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1313-L1315)

### to_json

```python
def to_json(self) -> str:
```

Return a Rust-validated declaration, including edits to nested models.

[Source: python/yosoi/policy.py:1317](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1317-L1319)

### identity

```python
def identity(self) -> PolicyIdentity:
```

Validate and return the Rust identity of resolved policy behavior.

Returns:
    Versioned canonical digest, independent of subsequent caller edits.

Raises:
    PolicyError: Complete policy validation or identity resolution fails.

[Source: python/yosoi/policy.py:1321](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1321-L1332)

### effective_policy

```python
def effective_policy(self) -> EffectivePolicy:
```

Return Current selections resolved by the Rust policy registry.

[Source: python/yosoi/policy.py:1334](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1334-L1338)

### snapshot

```python
def snapshot(self) -> PolicySnapshot:
```

Return the immutable Rust-validated declaration and behavior.

[Source: python/yosoi/policy.py:1340](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1340-L1342)

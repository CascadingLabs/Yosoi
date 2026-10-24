---
title: "Search"
description: "yosoi.policy.Search Python API reference."
order: 0
---

`yosoi.policy.Search`

```python
class Search(Model):
```

Ordered provider selection with shared search resource budgets.

Attributes:
    providers: Authored provider slots, at most three and without duplicates after
        validation.
    max_in_flight: Positive maximum simultaneous provider work.
    max_browser_in_flight: Positive maximum browser-backed provider work, separate
        from total concurrency.
    max_results_per_provider: Positive u16 retained organic-result limit for each
        provider.
    max_total_results: Positive u32 shared result capacity; validation checks the
        selected plan fits.
    max_retained_content_bytes: Positive addressable shared URL/text retention byte
        budget.
    maximum_elapsed: Positive shared search elapsed budget in microseconds.

[Source: python/yosoi/policy.py:685](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L685-L873)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
providers: Annotated[list[ProviderSelection], Field(max_length=3)] = _field('search', 'providers')
max_in_flight: PositiveInt = _field('search', 'max_in_flight')
max_browser_in_flight: PositiveInt = _field('search', 'max_browser_in_flight')
max_results_per_provider: PositiveU16 = _field('search', 'max_results_per_provider')
max_total_results: PositiveU32 = _field('search', 'max_total_results')
max_retained_content_bytes: AddressableByteLimitValue = _field('search', 'max_retained_content_bytes')
maximum_elapsed: MaximumElapsedValue = _field('search', 'maximum_elapsed')
```

## Methods

### disabled

```python
@classmethod
def disabled(cls) -> Self:
```

Return a validated search declaration selecting no provider routes.

[Source: python/yosoi/policy.py:716](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L716-L718)

### is_enabled

```python
def is_enabled(self) -> bool:
```

Return whether at least one provider is selected, not whether it can run.

[Source: python/yosoi/policy.py:720](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L720-L724)

### with_max_in_flight

```python
def with_max_in_flight(self, value: int) -> Self:
```

Return revalidated search limits without changing this declaration.

Args:
    value: Positive bound measured in simultaneous provider operations.

Returns:
    A new declaration checked by the Rust policy implementation.

Raises:
    PolicyError: Width, positivity, addressability, or plan consistency fails.

[Source: python/yosoi/policy.py:726](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L726-L745)

### with_max_browser_in_flight

```python
def with_max_browser_in_flight(self, value: int) -> Self:
```

Return revalidated search limits without changing this declaration.

Args:
    value: Positive bound measured in simultaneous browser-backed provider
        operations.

Returns:
    A new declaration checked by the Rust policy implementation.

Raises:
    PolicyError: Width, positivity, addressability, or plan consistency fails.

[Source: python/yosoi/policy.py:747](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L747-L767)

### per_provider_limit

```python
def per_provider_limit(self, value: int) -> Self:
```

Return revalidated search limits without changing this declaration.

Args:
    value: Positive bound measured in retained organic hits per provider.

Returns:
    A new declaration checked by the Rust policy implementation.

Raises:
    PolicyError: Width, positivity, addressability, or plan consistency fails.

[Source: python/yosoi/policy.py:769](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L769-L788)

### with_result_limits

```python
def with_result_limits(self, per_provider: int, total: int) -> Self:
```

Return a search declaration with explicit per-provider and shared limits.

Args:
    per_provider: Positive u16 retained-hit limit for each provider.
    total: Positive u32 shared retained-hit capacity.

Returns:
    A revalidated copy; this declaration is not mutated.

Raises:
    PolicyError: Width, positivity, or selected-plan capacity checks fail.

[Source: python/yosoi/policy.py:790](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L790-L810)

### with_max_total_results

```python
def with_max_total_results(self, value: int) -> Self:
```

Return revalidated search limits without changing this declaration.

Args:
    value: Positive bound measured in shared retained organic hits.

Returns:
    A new declaration checked by the Rust policy implementation.

Raises:
    PolicyError: Width, positivity, addressability, or plan consistency fails.

[Source: python/yosoi/policy.py:812](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L812-L831)

### with_max_retained_content_bytes

```python
def with_max_retained_content_bytes(self, value: int) -> Self:
```

Return revalidated search limits without changing this declaration.

Args:
    value: Positive bound measured in shared retained URL/text bytes.

Returns:
    A new declaration checked by the Rust policy implementation.

Raises:
    PolicyError: Width, positivity, addressability, or plan consistency fails.

[Source: python/yosoi/policy.py:833](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L833-L852)

### with_maximum_elapsed

```python
def with_maximum_elapsed(self, value: int) -> Self:
```

Return revalidated search limits without changing this declaration.

Args:
    value: Positive bound measured in shared elapsed microseconds.

Returns:
    A new declaration checked by the Rust policy implementation.

Raises:
    PolicyError: Width, positivity, addressability, or plan consistency fails.

[Source: python/yosoi/policy.py:854](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L854-L873)

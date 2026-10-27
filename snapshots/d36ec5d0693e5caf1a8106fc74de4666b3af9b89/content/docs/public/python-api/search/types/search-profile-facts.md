---
title: "SearchProfileFacts"
description: "yosoi.search.SearchProfileFacts Python API reference."
order: 0
---

`yosoi.search.SearchProfileFacts`

```python
class SearchProfileFacts(ImmutableModel):
```

Content-free route-selection and effective-policy facts for one provider.

Attributes:
    acquisition: Selected acquisition mechanism, absent when no route resolved.
    defaults_status: Certification state of the defaults used for route selection.
    defaults_version: Package-owned defaults version, absent for routes without such
        defaults.
    effective_request_policy: Resolved Requests policy identity, absent when no
        Request was prepared.

[Source: python/yosoi/search.py:481](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/search.py#L481-L496)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisition: AcquisitionKind | None
defaults_status: ProviderDefaultsStatus
defaults_version: int | None
effective_request_policy: PolicyIdentity | None
```

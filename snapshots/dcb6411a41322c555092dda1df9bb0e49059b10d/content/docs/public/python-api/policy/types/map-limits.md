---
title: "MapLimits"
description: "yosoi.policy.MapLimits Python API reference."
order: 0
---

`yosoi.policy.MapLimits`

```python
class MapLimits(Model):
```

Map discovery counts, retention bounds, and execution budgets.

Attributes:
    max_link_depth: Maximum rooted hyperlink depth; zero permits root-only
        exploration.
    max_hosts: Positive maximum retained hostnames.
    max_urls: Positive maximum retained normalized page URLs.
    max_relationships: Positive maximum directed relationships retained.
    max_observations: Positive maximum provenance observations retained.
    max_pending: Positive maximum pending frontier entries.
    max_requests: Positive charged acquisition request count, including support
        sources.
    max_sitemaps: Positive maximum sitemap sources processed.
    max_sitemap_depth: Maximum nested sitemap depth.
    max_response_bytes: Positive maximum bytes in one acquired response.
    max_total_response_bytes: Positive aggregate acquired-response byte budget.
    max_retained_document_bytes: Positive retained document payload budget, distinct
        from inventory metadata.
    max_concurrency: Positive maximum simultaneous acquisition work; this does not
        grant tab ownership.
    maximum_elapsed: Elapsed discovery budget expressed as seconds plus nanoseconds.
    max_url_bytes: Positive maximum normalized URL UTF-8 bytes.
    max_inventory_bytes: Positive byte budget for retained discovery inventory.
    max_parser_entries: Positive maximum source-parser entries examined.
    max_hostname_bytes: Positive maximum canonical hostname UTF-8 bytes.

[Source: python/yosoi/policy.py:477](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L477-L526)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_link_depth: U16 = _field('map', 'limits', 'max_link_depth')
max_hosts: BudgetValue = _field('map', 'limits', 'max_hosts')
max_urls: BudgetValue = _field('map', 'limits', 'max_urls')
max_relationships: BudgetValue = _field('map', 'limits', 'max_relationships')
max_observations: BudgetValue = _field('map', 'limits', 'max_observations')
max_pending: BudgetValue = _field('map', 'limits', 'max_pending')
max_requests: BudgetValue = _field('map', 'limits', 'max_requests')
max_sitemaps: BudgetValue = _field('map', 'limits', 'max_sitemaps')
max_sitemap_depth: U16 = _field('map', 'limits', 'max_sitemap_depth')
max_response_bytes: BudgetValue = _field('map', 'limits', 'max_response_bytes')
max_total_response_bytes: BudgetValue = _field('map', 'limits', 'max_total_response_bytes')
max_retained_document_bytes: BudgetValue = _field('map', 'limits', 'max_retained_document_bytes')
max_concurrency: BudgetValue = _field('map', 'limits', 'max_concurrency')
maximum_elapsed: Duration = _field('map', 'limits', 'maximum_elapsed')
max_url_bytes: BudgetValue = _field('map', 'limits', 'max_url_bytes')
max_inventory_bytes: BudgetValue = _field('map', 'limits', 'max_inventory_bytes')
max_parser_entries: BudgetValue = _field('map', 'limits', 'max_parser_entries')
max_hostname_bytes: BudgetValue = _field('map', 'limits', 'max_hostname_bytes')
```

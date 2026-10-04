---
title: Search
description: Find candidate URLs across search providers.
order: 2
---

# Search

Search returns candidate URLs and provider outcomes. Fetch a result separately when you need its document.

```sh
yosoi search "rust programming language" --providers bing --json
```

## Common options

| Option | Purpose |
| --- | --- |
| `--providers` | Choose an ordered provider list |
| `--per-provider-limit` | Bound results per provider |
| `--stats` | Write run statistics to stderr |

## Provider status

Current provider routes are previews. A provider may return partial results, be challenged, or fail independently of the others.

Use `yosoi search --help` for the full option list.

See [SDK Search](../sdk/search.md) for the integration model.

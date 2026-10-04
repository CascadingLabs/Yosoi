---
title: Map
description: Discover pages and inspect a site inventory.
order: 1
---

# Map

Start from a URL and discover pages within the configured scope and limits.

```sh
yosoi map https://example.org/ --json
```

## Common options

| Option | Purpose |
| --- | --- |
| `--json` | Emit ordinary JSON |
| `--max-concurrency` | Limit concurrent work |
| `--stats` | Write run statistics to stderr |

## Read the result

The JSON includes pages, source observations, and unfinished work. Inspect termination and partial results before using the inventory downstream.

Use `yosoi map --help` for the full option list.

Try [Discover and fetch](../cookbook/discover-and-fetch.md), or see [SDK Map](../sdk/map.md).

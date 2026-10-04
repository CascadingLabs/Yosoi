---
title: Extract structured data
description: Select values from HTML and JSON documents.
order: 2
---

# Extract structured data

Use Locate to turn a document into selected values.

## Select headings from a page

```sh
set -o pipefail
yosoi request https://example.org/ | yosoi locate --css 'h1' --json
```

## Select URLs from saved JSON

```sh
yosoi map https://example.org/ --json > map.json
yosoi locate --file map.json --format json --json-path '$.pages[*].url' --json
```

## When to use Contracts

For richer records, define the fields you need, extract candidates, and validate them with Contracts. A later recipe will show that workflow end to end.

Browse the [SDK](../sdk/index.md) for the module overview.

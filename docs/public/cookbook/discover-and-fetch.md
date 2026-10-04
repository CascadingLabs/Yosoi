---
title: Discover and fetch
description: Find pages on a site, then fetch one.
order: 1
---

# Discover and fetch

Use Map to discover candidate pages before deciding which ones to fetch.

## 1. Discover pages

```sh
yosoi map https://example.org/ --json > map.json
```

## 2. List their URLs

```sh
yosoi locate --file map.json --format json --json-path '$.pages[*].url' --json
```

## 3. Fetch a selected page

Copy one URL from the results:

```sh
yosoi request https://example.org/ --raw > page.html
```

Map returns a bounded inventory. A completed run does not guarantee every page on the site was found.

See [CLI Map](../cli/map.md) for output and limits.

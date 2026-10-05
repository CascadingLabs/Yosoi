---
title: CLI
description: Use Yosoi from your terminal.
order: 3
---

# CLI

The CLI exposes Yosoi operations as commands you can combine in shell workflows.

```sh
yosoi --help
```

| Command         | Purpose                       |
| --------------- | ----------------------------- |
| `yosoi request` | Fetch a document              |
| `yosoi locate`  | Select values from a document |
| `yosoi map`     | Discover site URLs            |
| `yosoi search`  | Query search providers        |

- [Map](map.md)
- [Search](search.md)

## Output

Use `--json` for ordinary JSON, `--raw` for document bytes, and typed document pipes when combining Request with Locate.

Start with the [quickstart](../quickstart.md) for installation.

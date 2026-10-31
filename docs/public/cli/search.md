---
title: Search
description: Find candidate URLs across search providers.
order: 2
---

# Search

Search returns candidate URLs and provider outcomes. Fetch a result separately when you need its document.

```sh
yosoi search "photosynthesis" --provider bing --output json
```

## Common options

| Option                            | Purpose                                  |
| --------------------------------- | ---------------------------------------- |
| `--providers`, `--provider`, `-p` | Choose an ordered provider list          |
| `--per-provider-limit`            | Bound results per provider               |
| `--max-in-flight`                 | Bound concurrent provider work           |
| `--diagnostics DIR`, `-d DIR`     | Save bounded evidence for offline replay |
| `--output json`                   | Write the structured result              |
| `--stats`, `-s`                   | Write run statistics to stderr           |

Choose from `google`, `brave`, `bing`, and `duckduckgo`. Specify one provider
to send a query to that provider alone. A comma-separated list selects multiple
providers; `--max-in-flight 1` runs their work serially.

## Save evidence and replay it

Diagnostic capture is optional. Add `-d` when you need to reproduce a parser
decision after a live query:

```sh
yosoi search "photosynthesis" --provider bing \
  --diagnostics search-evidence --per-provider-limit 3 -s
```

Search prints the result and a `Search evidence: ...json` path. Use that exact
path with the nested replay command:

```sh
yosoi search replay search-evidence/search-REQUEST_ID.json
```

Replay restores saved documents through Archive and makes no provider request.
Its report includes the saved and current decisions, `record_count`, and
`all_match`. A matching failed decision reproduces a failure; it does not turn
that failure into useful search results. Exit 1 means a decision changed, and
exit 2 means no replay documents were retained.

Omit `--diagnostics` for ordinary searches without retained replay documents.
`-s` independently enables statistics. Captures contain query/page content;
inspect them before sharing. Whole documents that exceed the capture quota are
omitted, with the gap recorded in attempt retention facts.

## Provider status

Current provider routes are previews. A provider may return partial results, be challenged, or fail independently of the others.

Use `yosoi search --help` for the full option list.

See [SDK Search](../sdk/search.md) for the integration model.
The [capture and replay guide](../sdk/search-diagnostics.md) uses the same evidence
through Rust and Python.

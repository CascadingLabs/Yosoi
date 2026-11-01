---
title: Search
description: Find candidate URLs across search providers.
order: 2
---

# Search

Search defaults to Auto routing: choose one eligible provider from the configured candidates, using shared Registry rotation. Fetch a result URL separately when you need its document.

```sh
yosoi search "photosynthesis" --provider bing --output json
```

## Common options

| Option                            | Purpose                                  |
| --------------------------------- | ---------------------------------------- |
| `--providers`, `--provider`, `-p` | Choose an ordered Auto candidate list    |
| `--routing auto`, `--routing all` | Choose one candidate or execute all      |
| `--per-provider-limit`            | Bound results per provider               |
| `--max-in-flight`                 | Bound concurrent provider work           |
| `--diagnostics DIR`, `-d DIR`     | Save bounded evidence for offline replay |
| `--output json`                   | Write the structured result              |
| `--stats`, `-s`                   | Write run statistics to stderr           |

Choose from `google`, `brave`, `bing`, and `duckduckgo`. Specify one provider
to send a query to that provider alone. A comma-separated list restricts Auto's candidates; it still selects one provider. Add `--routing all` to execute every listed provider, and `--max-in-flight 1` to run that explicit plan serially.

Without a provider list, Auto rotates Google → DuckDuckGo → Bing → Brave. The JSON result includes `routing`, `selected_provider` and the correlated `rotation` trace. Unsupported or constrained candidates retain not-started reasons; `not_selected` means Auto chose another provider. No eligible candidate means no outbound provider work, and a provider failure never causes an engine switch.

Use `--registry ./search.jsonl` for a workload-specific state file. Otherwise, Auto uses the Respectfulness policy's registry path or the standard per-user Registry file. Rotation survives process exit. Authored Respectfulness rules apply to admission; with no policy, those controls remain disabled.

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

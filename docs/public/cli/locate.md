---
title: 'Locate values'
description: 'Query a local file, raw stdin or one typed Yosoi Document.'
order: 0
---

# Locate values

Locate evaluates a query against supplied evidence. It does not fetch a URL. This first example uses a local HTML fixture.

## Read a local heading

```sh
printf '%s\n' '<main><h1>Hello, Yosoi</h1></main>' > page.html
yosoi locate --file page.html --format html --css 'h1' --json
```

The JSON envelope reports the Locate outcome. Inspect its status and findings before using a selected value.

## Choose one input

| Input                         | Flags                         |
| ----------------------------- | ----------------------------- |
| Raw file                      | `--file PATH --format FORMAT` |
| Raw stdin                     | `--stdin --format FORMAT`     |
| Typed Yosoi Document on stdin | `--pipe-document`             |

Raw formats are HTML, XML, JSON and text. A typed frame already carries its representation profile. Choose exactly one input source.

## Read a JSON value

```sh
printf '%s\n' '{"shop":"Corner"}' > shop.json
yosoi locate --file shop.json --format json --json-pointer '/shop' --json
```

JSON Pointer projects the selected JSON value. Use `--json-path` for the supported JSONPath subset. CSS and literal text have their own selector flags; choose exactly one query per command.

## Combine with Request

```sh
set -o pipefail
yosoi request https://example.org/ --pipe-document | yosoi locate --pipe-document --css 'h1' --json
```

The explicit frame format preserves Document identity and profile between commands. For an ordinary byte pipeline, declare its raw format instead.

## Interpret absence and failure

Matched, no match, indeterminate and failed outcomes preserve different facts. An unsupported Plan or incompatible projection is a configuration error, while complete evidence with no matching node can produce no match.

Use `--full` to expand human-readable values and `--stats` for operation statistics on stderr. See [Choose a locator](../cookbook/choose-a-locator.md) or `yosoi locate --help`.

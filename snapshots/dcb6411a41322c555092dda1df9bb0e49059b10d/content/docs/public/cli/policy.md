---
title: 'Policy profiles'
description: 'Inspect and validate the configuration used by CLI operations.'
order: 0
---

# Policy profiles

The CLI can load named JSON-authored Policy profiles. These inspection commands do not create or overwrite profiles.

## Inspect the store

```sh
yosoi policy path
yosoi policy list
yosoi policy validate
```

The first command prints the store location. The second lists saved profiles and marks the active one. Validation checks the active effective Policy or the defaults when no profile is selected.

## Author a profile

Save JSON at the path reported by `yosoi policy path`. If a store already exists,
add the profile to its version bucket and retain the other entries. This example
uses the `0.2.0` CLI bucket and a five-second per-attempt limit:

```json
{
  "format_version": 1,
  "cli_versions": {
    "0.2.0": {
      "profiles": {
        "research": {
          "request": { "maximum_elapsed": 5000000 }
        }
      }
    }
  }
}
```

Check `yosoi --version` and use the matching version key. The stored setting is
in microseconds; Request CLI `--timeout-ms` is in milliseconds. Validate the
profile before running a task with it.

## Select a saved profile

For a profile already saved as `research`:

```sh
yosoi policy validate research
yosoi --profile research request https://example.org/ --json
```

The profile name refers to real configuration in the store. Use a name present in `policy list`; the example does not create a profile called `research`.

## See the operation's choices

```sh
yosoi request https://example.org/ --explain
```

Explain mode validates and displays the Request's Policy before acquisition. Command-specific bounds can override supported settings for that operation.

Use [Policy and budgets](../concepts/policy-and-budgets.md) for the shared model and [SDK Policy](../sdk/policy.md) to author declarations in application code.

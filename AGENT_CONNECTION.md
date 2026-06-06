# Shared Agent Connection

Updated: 2026-06-05

Active tree: `/home/andrew/Desktop/cl/Yosoi-spike-hotpath`
Active branch: `spike/hotpath-dogfood`

## What Was Consolidated

- Hotpath spike work is the code authority for browser identity, replay, SERP dogfood, and multi-url/multi-contract scrape behavior.
- Claude CAS-96 worktree was merged into this branch:
  `andberg9/cas-96-agent-driven-cli-canonicalized-contracts-mcp-out-of-scope`.
- CAS-83 scope branch was recorded as merged, but its stale broad repo churn was intentionally not applied over the hotpath code. Its useful artifacts are restored under `experiments/scope_spike/`.

## Current Hotpath Surface

- `ys.scrape(url | [url], Contract | [Contract], ...)` supports the url x contract grid.
- `fetcher_type` can be scalar, `{url: tier}`, or `url -> tier`, so Google can run `headful` while Bing/Brave stay `headless`.
- `identities` is opt-in per URL via `BrowserIdentity` and threads into browser fetchers.
- `max_concurrency` caps concurrent `(url, contract)` units for large SERP grids.
- `BrowserIdentity.geo` is applied at fetch time when the live tab exposes `set_geolocation`.

## Contract/CLI Surface From CAS-96

- Canonical contract/spec work is now present:
  - `yosoi/models/spec.py`
  - `yosoi/models/needs_discovery.py`
  - `yosoi/storage/contracts_store.py`
  - `yosoi/core/resolve.py`
  - `yosoi/cli/contract_param.py`
  - `yosoi/cli/exit_codes.py`
- `Contract` now keeps both hotpath helpers and CAS-96 helpers:
  - `variant(...)`
  - `to_model(...)`
  - `frozen_fields()`
  - `to_spec()` / `from_spec(...)`

## Do Not Regress

- Keep `yosoi/core/pipeline/` as a package. CAS-96 had a flattened `yosoi/core/pipeline.py`; that was dropped during merge resolution because it would overwrite hotpath replay/download/browser identity work.
- Do not share one `DiscoveryBus` across distinct sibling contracts just because fields look identical. For SERP block discrimination, related contracts need to diverge, not dedup.
- CAS-83 artifacts are experiments only unless deliberately productized. Start at `experiments/scope_spike/SPIKE_REPORT.md`.

## Suggested Checks

- Focused API/browser identity checks:
  `uv run pytest tests/unit/test_api.py tests/unit/core/fetcher/test_voiddriver_geo.py`
- CAS-96 contract surface checks:
  `uv run pytest tests/unit/models/test_spec.py tests/unit/storage/test_contracts_store.py tests/unit/core/test_resolve.py tests/unit/cli/test_verb_group.py tests/unit/test_exit_codes.py tests/unit/test_frozen_fields.py`

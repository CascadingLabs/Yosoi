# A3Node replay and fragments

A3Node is Yosoi's experimental browser-action replay layer for rendered pages. It records the actions needed to make content visible, then replays them before HTML capture on later runs.

Enable it explicitly:

```bash
uv run yosoi fetch https://example.com --a3node
uv run yosoi scrape https://example.com/products/sku-1 --contract @Product --a3node
```

Recipe replay also enables A3Node automatically when the recipe carries `a3nodes`.

## Handwritten flows

`ys.Flow` is the experimental manual authoring surface for the same replay model.
Class-definition order becomes sequence order, each public attribute becomes a
stable node ID, and `ys.Expect[...]` supplies the post-action assertion:

```python
import yosoi as ys


class ResultsVisible(ys.State):
    condition = ys.css('.results')


class RevealResults(ys.Flow):
    open_results: ys.Expect[ResultsVisible] = ys.click(ys.role('tab', name='Results'))
```

A Flow compiles to `ReplayPlan`; it does not introduce another browser driver or
execution path. See [`executor-js-flow.md`](executor-js-flow.md) for executors,
module trees, live execution, and current alpha limitations.

## Scoped replay

A3Node recipes are no longer domain-only. New scope keys include:

- domain;
- normalized route path;
- query-key shape, excluding values;
- replay intent (`fetch`, scrape/action/download shape, etc.);
- browser/profile fingerprint such as tier, headless/headful state, identity id, locale, timezone, geo/proxy/user-agent hashes, and accept-language.

This prevents one page template, query surface, or browser identity from overwriting another just because they share a domain.

Storage lives in `.yosoi/yosoi.sqlite3` in the `a3nodes` table. Legacy domain-only rows are treated as legacy scopes instead of broad reusable authority.

## Fragment bank

Yosoi also learns small domain-free fragments for common obstacles:

- cookie banners;
- popups;
- age gates.

Fragments are keyed by stable target structure, not by source domain. Before scoped probing, Yosoi can try the best reusable fragments. A fragment miss is non-authoritative: if the target is absent or stale, it is skipped and normal scoped probing continues.

## Replay contract

Replay is conservative:

1. choose the scoped A3Node recipe before navigation;
2. replay stored concrete targets only if they are present;
3. ignore stale fragment/action targets instead of failing the whole fetch;
4. run the normal DOMLoader probe when replay does not provide enough action coverage;
5. save successful scoped acts and refresh reusable fragments.

No Playwright path exists; rendered behavior goes through VoidCrawl-backed fetchers.

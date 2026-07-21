# Browser Flows and typed executors

Yosoi `Flow` is the manually-authored path for deterministic browser interactions that should compile to the same A3 replay
model used by recipes. Use it after browser behavior and targets are understood; selector discovery remains the right tool when
they are not.

## Ordered browser flows

A `Flow` class is an ordered declaration. Actions execute in class-body order, and annotated `Executor.js` fields validate their
outputs before `Flow.run()` returns.

```python
import yosoi as ys


class CatalogFlow(ys.Flow):
    ready = ys.expect(
        ys.wait_until(max_attempts=40, interval_ms=250),
        ys.css('.catalog'),
    )
    load = ys.scroll_until(
        ys.nearest_scroll_parent(ys.css('.product-card')),
        max_scrolls=ys.input('max_scrolls'),
        stop_when='no_growth',
        stable_rounds=3,
    )
    titles: list[str] = ys.Executor.js(
        "Array.from(document.querySelectorAll('.product-card h2'), el => el.textContent.trim())",
        settle=ys.until.length_at_least(1, timeout=10),
    )


result = await CatalogFlow.run(
    'https://example.com/catalog',
    inputs={'max_scrolls': 20},
    timeout=120,
)
print(result.values['titles'])
```

`Flow.compile()` produces a `ReplayPlan` without opening a browser. This is useful for review, storage, and deterministic tests.
`Flow.run()` executes that plan through Yosoi's VoidCrawl-backed `HeadlessFetcher`; it does not introduce another browser driver.

## Actions and expectations

Public actions include:

- `click()` and bounded `click_all()`;
- `wait_until()` for repeated readiness checks;
- `scroll_until()` with an expectation or DOM-growth stopping policy;
- `collect_each()` for opening, extracting, closing, and deduplicating repeated dialogs;
- `Executor.js()` for typed page-scope evaluation.

Wrap an action with `ys.expect(action, condition)` when the next step depends on a postcondition. Conditions include CSS or
accessible-role targets, `count()`, `absent()`, and `dom_stable()`.

Runtime values are declared with `ys.input('name')` and supplied to `compile()` or `run()`. Missing inputs and repeat limits below
one fail during compilation.

## Confined JavaScript modules

Keep substantial page evaluators in a local ESM directory instead of interpolating source strings:

```python
from pathlib import Path

import yosoi as ys

JS = ys.Executor.js.modules(Path(__file__).with_name('_browser'))
EXTRACT_ROWS = JS.function('catalog.mjs', export='extractRows')


class CatalogRows(ys.Flow):
    rows: list[dict[str, str]] = ys.Executor.js(
        EXTRACT_ROWS,
        args={'region': ys.input('region')},
        settle=ys.until.length_at_least(1),
    )
```

The module loader is confined to its configured root, bundles only static relative named imports, rejects dynamic/default or
external imports, and fingerprints the bundled program. Runtime arguments are JSON encoded rather than interpolated into source.

## Failure behavior

Flows fail instead of inventing fallback selectors. A run fails when navigation, an interaction, a postcondition, evaluator
settling, or Pydantic output validation fails. Keep repeat, scroll, detail-page, and overall run budgets explicit. Application
matching, account mapping, and domain-specific extraction belong in the consuming application—not in Yosoi's public examples.

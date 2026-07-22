# JavaScript executors and handwritten browser flows

> [!WARNING]
> `ys.Executor.js` and `ys.Flow` are experimental alpha APIs. They are runnable,
> typed, and fail-fast, but their authoring details may change before beta.

Yosoi supports two related browser primitives:

- `ys.Executor.js(...)` returns a browser-computed value and validates it against
  its Python annotation.
- `ys.Flow` spells out a deterministic A3Node browser program when content must be
  revealed before it can be evaluated.

A Flow is not a second automation runtime. Its class declarations compile directly
into the existing `ReplayPlan` assess/act/expect model and execute through VoidCrawl.

## A typed JavaScript contract field

```python
import yosoi as ys


class RuntimeSignals(ys.Contract):
    title: str = ys.Executor.js('document.title')
    dimensions: dict[str, int] = ys.Executor.js(
        '(() => ({width: innerWidth, height: innerHeight}))()'
    )
```

The annotation remains the output schema. Required fields still fail validation when
execution produces `null`. Contract fields currently inherit `ys.js` batching semantics:
a per-field JavaScript exception is isolated as `null` before type validation. Flow
executors use replay EVAL acts and propagate JavaScript failures directly. Explicit
`settle=` conditions are Flow-only; Contract action fields use the browser fetcher's
existing batch-settle policy.

`ys.js(...)` remains available and compatible. `ys.Executor.js(...)` is the more
discoverable namespace for new code.

## Local `.js` and `.mjs` helpers

Large evaluators can live in a confined module tree:

```text
my_scraper/
├── contract.py
└── _js_helpers/
    ├── index.mjs
    └── cards.mjs
```

```javascript
// cards.mjs
export function extractCards({limit}) {
  return Array.from(document.querySelectorAll('article'))
    .slice(0, limit)
    .map((card) => ({title: card.querySelector('h2')?.innerText || ''}));
}
```

```javascript
// index.mjs
export {extractCards} from './cards.mjs';
```

```python
from pathlib import Path
import yosoi as ys

modules = ys.Executor.js.modules(Path(__file__).with_name('_js_helpers'))
extract_cards = modules.function('index.mjs', export='extractCards')


class Cards(ys.Contract):
    cards: list[dict[str, str]] = ys.Executor.js(
        extract_cards,
        args={'limit': 20},
    )
```

The loader:

- parses each file with the Tree-sitter JavaScript grammar before linking;
- confines every file beneath the declared root;
- accepts `.js` and `.mjs` files;
- supports named function exports and static relative named imports/re-exports without binding aliases;
- preserves each module's private scope, including repeated private binding names;
- rejects syntax errors, cycles, mutable live bindings, path traversal, package imports,
  default imports, and dynamic imports before browser execution;
- caps each file at 512 KB, the graph at 128 files and 2 MB, and the linked output at 2 MB;
- fingerprints the complete linked function expression;
- sends linked source to the browser, never a local path.

This is intentionally an AST-backed ESM subset, not a general JavaScript build system.

## Handwritten A3 flows

Use a class when browser state must change before evaluation:

```python
import yosoi as ys

ROW = ys.css('[data-row]')


class ItemsTabReady(ys.State):
    condition = ys.role('tab', name='Items')


class ItemsPanelOpen(ys.State):
    condition = ys.css('[role="menu"]')


class CardLimitLoaded(ys.State):
    condition = ys.count(ROW, at_least=ys.input('limit'))


class LoadCards(ys.Flow):
    panel_ready: ys.Expect[ItemsTabReady] = ys.wait_until(
        max_attempts=20,
        interval_ms=250,
    )

    open_panel: ys.Expect[ItemsPanelOpen] = ys.click(ys.role('tab', name='Items'))

    load_rows: ys.Expect[CardLimitLoaded] = ys.scroll_until(
        ys.nearest_scroll_parent(ROW),
        max_scrolls=ys.input('max_scrolls'),
    )

    cards: list[dict[str, str]] = ys.Executor.js(
        extract_cards,
        args={'limit': ys.input('limit')},
        settle=ys.until.length_at_least(1, timeout=5, poll_interval=0.25),
    )
```

Run it through a live browser:

```python
result = await LoadCards.run(
    'https://example.com/items',
    inputs={'limit': 20, 'max_scrolls': 10},
    fetcher_type='headless',
)
print(result.values['cards'])
```

### Flow declaration rules

- Class-definition order is sequence order.
- A public attribute name is the stable A3Node ID.
- `ys.State` names a reusable selector/condition, and `ys.Expect[ThatState]`
  becomes the node's post-action assertion.
- `ys.Executor.js` fields require either an ordinary output annotation or an
  `ys.Expect[...]` state. Output annotations validate captured values, and the
  attribute name becomes `output_field`.
- Missing inputs, unresolved annotations, failed actions, failed expectations, and
  Flow executor settle timeouts fail loudly.
- Repeated `wait_until` and `scroll_until` actions require an `ys.Expect[...]` state.
- `click`, `click_all`, `wait_until`, and `scroll_until` lower to deterministic A3
  acts; they do not introduce a second browser driver.

Runtime inputs are valid only on Flow executor fields. Contract executor arguments
must be literal because a Contract has no Flow input scope.

## Current alpha limits

- `Flow.run` currently supports the headless and headful VoidCrawl fetchers.
- Executor scope is page-level only.
- Flow classes currently compile a flat A3 sequence; public Sequence, Selector, and
  Reaction authoring helpers remain future work.
- Local module loading implements a constrained, acyclic ESM subset and rejects named import/export aliases, mutable live bindings, side-effect-only imports, and top-level await.
- Flow declarations do not yet automatically mint or install recipes.
- Domain-specific extraction and interaction flows belong in consuming applications.

# Observation index pruning — high-level examples

This is the explanation to use when describing the QA index without walking through the
implementation.

## The one-sentence model

Yosoi keeps the original evidence intact, then builds a small map of the page. The QA agent
starts with the map and asks for exact detail only where the map points.

```text
canonical page evidence
        │
        ▼
compact index ──inspect──▶ exact element or subtree
        │
        └──expand──▶ members of a repeated region
```

Pruning is therefore **semantic compression**, not deleting HTML. A summary may be small, but
every address must still resolve back to the immutable artifact that produced it.

## What the index shows

A normal element is represented by one entry:

```text
h1                         "All products"
/html/body/.../h1
```

A repeated structure is represented by a region and an exemplar instead of one entry per row:

```text
ol.row > li.product       ×20 products
.../ol#shape=d0f03606

li.product                 exemplar of ×20
.../ol#shape=d0f03606&key=text:afe617...
```

The region says “there are 20 members with this shape.” `expand` can then return bounded pages
of members. A member gets a content key when possible; if no unique key exists, the address says
that it is positional and therefore unstable.

## Site examples from the spike corpus

These examples are deliberately different. The goal is not to make every site look like a
successful compression case; it is to show where each evidence modality and limitation matters.

### Books to Scrape — clean static control

**Shape:** server-rendered HTML with 20 repeated product cards.

```text
51 KB source HTML
  ├── declarations: title, meta, links, scripts
  └── body: page structure + 20 product cards

index:
  ├── one product region (×20)
  ├── one product exemplar
  └── one-hop declarations such as robots, description, favicon, and jQuery
```

This is the current L1 dogfood case. The frozen capture produces 79 entries and about 3.2 KB
of summaries. The 20 products remain individually reachable through `expand`; the source bytes
are never replaced by the summary.

### Wikipedia — negative control for over-pruning

**Shape:** a large page dominated by unique prose rather than repeated records.

```text
article
  ├── lead prose
  ├── history prose
  ├── references
  └── tables and navigation
```

The desired behavior is *not* to force a dramatic compression ratio. Unique prose should remain
represented as meaningful structure. If this page compresses as aggressively as a product grid,
the reducer is probably treating content as repetition merely because the surrounding tags look
similar.

### RealWorld Conduit — static HTML is insufficient

**Shape:** client-rendered SPA whose useful feed and article content arrive after hydration.

```text
source HTML:     application shell, often little useful content
rendered DOM:    feed cards, article detail, controls
network evidence: REST responses that populated the page
```

This is not an HTML-pruner failure. It demonstrates the capture ladder: L1 source HTML can say
what the server delivered, while the DOM and network modalities are needed to explain what the
user actually saw.

### Saleor Storefront — cross-modality consistency

**Shape:** GraphQL-backed storefront with server/client state.

```text
network:  products requested
DOM:      products rendered
QA check: requested count versus rendered count
```

The useful index is not just a smaller DOM. It must preserve enough network and rendered evidence
to notice disagreements, such as an API returning 24 products while only 20 appear on screen.

### React Window / virtualized lists — explicit incompleteness

**Shape:** only the visible slice exists in the DOM at one time.

```text
snapshot_0: rows 0–19 observed
scroll
snapshot_1: rows 20–39 observed
```

A single snapshot must not claim that the first 20 rows are the whole list. The region carries
coverage information, and the broader QA model treats scrolling as an episode with multiple
snapshots and a bounded diff.

### Google Maps, news aggregators, and other dense pages — navigation pressure

The earlier spike also exercised dense, highly nested pages and repeated article/card content.
The lesson was consistent: the index should stay flat and route the agent to likely regions,
not build a deeply nested representation that requires several routing decisions before detail.

These pages are useful demonstrations of the *navigation* benefit even when their content is
too dynamic or noisy to serve as a deterministic L1 gate.

### Dirty production pages — canary, not gate

Examples such as major news and commerce sites contain consent walls, ad slots, tag managers,
telemetry, lazy hydration, and anti-bot behavior.

```text
clean fixture:      deterministic regression gate
frozen dogfood:     realistic behavior signal
live dirty target:  drift and failure-shape discovery only
```

A dirty page failing to capture does not automatically mean the pruning algorithm is wrong. It
may identify a fetch or browser-tier problem, which belongs to a different layer.

## What pruning is optimizing

The index is optimizing for three things at once:

1. **Reachability:** important evidence is one bounded inspection hop away.
2. **Compression:** repeated structure does not consume one index slot per member.
3. **Honesty:** omissions, positional fallbacks, unavailable modalities, and incomplete regions
   are explicit rather than silently presented as complete evidence.

The success criterion is therefore not “smallest HTML.” It is “small enough to navigate while
still making the evidence needed to detect defects discoverable.”

## Current L1 boundary

Implemented now:

- static source-HTML declarations;
- contiguous repeated-sibling collapse;
- stable-or-explicitly-unstable member addressing;
- exact one-hop inspection and bounded region expansion;
- deterministic offline boss fights.

Still intentionally later:

- non-contiguous record clustering;
- rendered DOM and accessibility-tree pruning;
- network pruning;
- token-budget rendering;
- multi-snapshot diffing and action episodes;
- wiring into normal Yosoi QA operations.

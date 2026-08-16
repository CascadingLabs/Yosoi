# Observation Pruning Boss Fights

Boss fights are adversarial evaluation workloads for Yosoi's modality-specific observation pruners. They test whether a compact index keeps important evidence directly discoverable without task-conditioned pruning.

They are organized around orthogonal failure shapes rather than website popularity.

## Principles

1. Every pruning mode gets both a controlled boss fight and real-world dogfood.
2. Controlled and pinned fixtures gate CI; live sites never gate.
3. Capture profiles and evidence modalities remain independent concepts.
4. Canonical policy-safe artifacts survive pruning unchanged.
5. A small index must lead to exact evidence through stable, snapshot-bound references.
6. Predictions and required evidence references are written before measuring a pruner.
7. Missing modalities are explicit capabilities, never silently represented as empty evidence.
8. Initial targets require no authentication, signup, onboarding, API keys, or credential handoff.

## Evaluation ownership

```text
tests/evals/observations/   pruning, reachability, budgets, determinism
tests/evals/qa/             MDS coverage correlated with QA defect detection
tests/evals/discovery/      later selector/extractor discovery effectiveness
```

Passing the observation or QA gate does not automatically prove discovery fitness.

## Corpus lanes

| Lane | Purpose | Gating |
| --- | --- | --- |
| `gate` | Controlled, pinned, reproducible fixtures with known ground truth | Yes |
| `selfhost` | Version-pinned local applications with preseeded state | Yes after capture stability is proven |
| `dogfood` | Frozen captures from realistic public applications | Regression signal only |
| `live` | Current public deployments used to detect drift and new failure shapes | Never |

Public deployments should be frozen into policy-safe artifacts before deterministic evaluation. Live access is for collecting new evidence, not for CI assertions.

## Pruning modes

### HTML pruning

**Threat:** repetitive chrome or deduplication destroys unique source content, malformed markup breaks addressing, or a fixed budget hides a buried defect.

Controlled boss fight:

- A generated server-rendered document containing:
  - unique long-form prose;
  - repeated navigation and footer chrome;
  - large tables and repeated records;
  - malformed and noisy legacy markup;
  - deeply buried links and values;
  - one injected defect per failure class.

Dogfood targets:

- Wikipedia article pinned to an exact `oldid`.
- A frozen, large Hacker News comment thread.
- Books to Scrape as the clean SSR control.

Intentions:

- Wikipedia is the negative control: unique prose must not be mistaken for removable repetition.
- Hacker News stresses deeply nested, repetitive comments and links.
- Books to Scrape should be nearly solvable from source HTML alone.

### DOM pruning

**Threat:** rendered state, visibility, virtualized content, portals, hidden trees, and offscreen elements are flattened or discarded incorrectly.

Controlled boss fight:

- A QScrape fixture containing:
  - at least 10,000 DOM nodes;
  - 95% hidden or offscreen content;
  - virtualized rows;
  - modal and portal content;
  - shadow DOM;
  - duplicate-looking regions with different state;
  - one defect available only after a scroll or action episode.

Dogfood targets:

- AG Grid examples.
- TanStack Virtual infinite-scroll example.
- QScrape L2 applications.
- Anonymous portions of Saleor Storefront and OWASP Juice Shop.

Intentions:

- AG Grid stresses virtualized rows/columns and rich grid state.
- TanStack Virtual proves that a single snapshot is structurally insufficient.
- QScrape provides deterministic ground truth and injectable failures.

Virtualization is evaluated as an episode:

```text
Episode
├── snapshot_0
├── scroll/action
├── snapshot_1
└── bounded diff
```

A single-snapshot pruner should report incomplete capabilities rather than pretend all virtual content was observed.

### AX pruning

**Threat:** useful semantics, names, roles, states, relationships, or controls disappear during compaction—or AX is incorrectly treated as a complete representation of the visible page.

Controlled boss fight:

- An ARIA-heavy fixture containing:
  - grids, comboboxes, tabs, dialogs, treeviews, and forms;
  - repeated controls with state differences;
  - useful semantics present only in AX;
  - a paired defect visible in DOM but absent from AX;
  - a paired defect obvious in AX but difficult to infer from DOM.

Dogfood targets:

- AG Grid examples.
- A public ARIA Authoring Practices example or comparable accessible component suite.
- A GOV.UK-style accessible form fixture.
- Monaco Editor as a later keyboard/virtualized-text stress target.

Intentions:

- AX and DOM remain complementary modalities.
- The AX pruner must preserve role, accessible name, state, and relationships.
- AX absence must never be interpreted as proof that visible information does not exist.

### Network pruning

**Threat:** a small number of important API failures disappear among assets, telemetry, duplicate calls, and irrelevant JSON.

Controlled boss fight:

- A seeded, already-normalized and redacted trace with exactly 400 requests:

```text
400 requests
├── 250 assets
├── 80 analytics/ad/telemetry
├── 40 duplicate API calls
├── 20 irrelevant JSON calls
├── 8 useful API calls
└── 2 requests containing the actual defect
```

The two defect-bearing requests must be discoverable from an approximately 1,000–3,000-token overview without providing the task in advance.

Dogfood targets:

- Saleor Storefront GraphQL traffic.
- Anonymous OWASP Juice Shop REST traffic.
- QScrape controlled API-backed applications.
- Netdata real-time dashboard traffic.
- Grafana polling/dashboard traffic with anonymous viewing enabled.
- OpenStreetMap request volume and dynamic overlays, excluding visual correctness.

Intentions:

- Inputs are normalized and redacted before the network pruner sees them.
- Credentials, cookies, authorization headers, sensitive query values, and raw protected bodies never enter ordinary model-visible fixtures.
- Duplicate requests remain countable even when represented compactly.
- Important non-2xx statuses, response-shape changes, and API/DOM cardinality mismatches remain addressable.

## No-auth SPA slate

Initial SPA targets must open directly into the test state.

| Target | Allowed anonymous scope | Primary pressure |
| --- | --- | --- |
| AG Grid examples | Public or local examples | Virtualized DOM and AX grid semantics |
| TanStack Virtual examples | Public or local examples | Multi-snapshot scrolling and disappearing nodes |
| RealWorld Conduit | Public feed and article browsing | CSR REST list/detail control |
| Saleor Storefront | Catalog, filters, pagination, anonymous cart | GraphQL, hydration, client/server state |
| OWASP Juice Shop | Anonymous storefront browsing | Angular DOM, REST, dialogs, error states |
| Node-RED | Local editor, bound only to localhost | Large interactive editor and changing graph metadata |
| Grafana | Local anonymous viewer with preprovisioned dashboards | Dense dynamic dashboards and polling |
| Netdata | Local dashboard without cloud integration | High-frequency live updates and network noise |
| OpenStreetMap | Public anonymous browsing | Request volume and dynamic overlays |

Deferred until authentication work exists:

- ChatGPT itself.
- Mattermost and Rocket.Chat.
- Twenty and other account-first business applications.
- Authenticated Saleor or Juice Shop paths.
- Open WebUI unless auth-disabled operation is proven stable and preseeded.

Local applications must be preseeded before launch. QA must not provision data or create accounts through the browser.

## Boss-fight manifest

Each workload records its prediction and gate before capture:

```toml
id = "wikipedia_unique_prose"
modality = "source_html"
lane = "dogfood"
threat = "deduplication destroys unique prose"
capture_profile = "http_static"
budget_tokens = 3000
max_inspection_hops = 1
required_refs = ["section:history", "table:demographics"]
failure = "a required reference is unreachable within the inspection budget"
```

The eventual manifest should also record:

- source URL or local fixture identity;
- immutable version, commit, image digest, or public capture timestamp;
- available and unavailable modalities;
- artifact digests;
- pruner name/version and policy hash;
- ground-truth defect and required evidence references;
- source, retained, and omitted item counts;
- output bytes/tokens;
- tokenizer identity;
- retrieval hops and cumulative retrieval tokens.

## Per-pruner gates

Every modality is evaluated for:

1. Byte-identical deterministic output for identical inputs and policy.
2. Exact resolution of every emitted reference.
3. Explicit failure for stale, foreign, or malformed references.
4. Modality-specific Minimal Defect Set reachability.
5. Overview and cumulative inspection token budgets.
6. Source/retained/omitted accounting.
7. Canonical artifact immutability.
8. Explicit capability reporting when evidence was unavailable.
9. Zero model-visible credential leakage.

## Cross-modality gate

The combined index should prove that complementary evidence remains available without one modality becoming authoritative over another.

Measure:

- required evidence reachable from the flat overview;
- number of inspection hops;
- overview and cumulative tokens;
- defects visible in one modality but absent from another;
- contradictions between DOM, AX, and network evidence;
- false confidence caused by missing or thin modalities.

## Initial delivery order

1. HTML controlled fixture, Books to Scrape, pinned Wikipedia, and frozen Hacker News thread.
2. QScrape DOM fixture plus AG Grid and TanStack Virtual captures.
3. Paired DOM/AX ARIA fixture and AG Grid AX capture.
4. Seeded 400-request network generator and scorer.
5. Anonymous Saleor, Juice Shop, Grafana, and Netdata dogfood captures.
6. Multi-snapshot episode corpus and bounded index diffs.
7. Cross-modality scoreboard and CI thresholds.

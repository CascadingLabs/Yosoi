# Consult: Scrapling adaptive selectors vs. our page fingerprint

_Source-read of `D4Vinci/Scrapling@main` (2026-06-06): `scrapling/core/utils/_utils.py`,
`storage.py`, `parser.py`, `mixins.py`. Quotes are exact symbol names from that tree._

## What Scrapling actually does

Scrapling's "auto-match / adaptive" feature re-finds **one previously-saved element** after a
site redesign. It is an **element-relocation** system, not a page-identity system.

### The element fingerprint — `_StorageTools.element_to_dict()` (`_utils.py:84`)
Every saved element serializes to this dict (exact keys):

| key | how it's computed |
|-----|-------------------|
| `tag` | `str(element.tag)` |
| `attributes` | `__clean_attributes` — `attrib` with empty/whitespace values dropped, values `.strip()`ed |
| `text` | `element.text.strip()` or `None` |
| `path` | `_get_element_path` — **tuple of ancestor tags from root → element** (recursive) |
| `parent_name` / `parent_attribs` / `parent_text` | the parent element's tag / attrib dict / text |
| `siblings` | `tuple(child.tag for child in parent.iterchildren() if child != element)` |
| `children` | `tuple(child.tag …)` (forbidden node types filtered) |

### Storage — `storage.py`
SQLite: `CREATE TABLE storage (id, url, identifier, element_data, UNIQUE(url, identifier))`.
`element_data = orjson.dumps(element_to_dict(...))`. The `url` column is the **base domain**
(full legal domain via the `tld` library, `_get_base_url`). The `identifier` is **author-supplied**.
So an element's identity is **`(domain, identifier)` — domain is load-bearing in the key.**

### Relocation — `__calculate_similarity_score` / `relocate` (`parser.py`)
On a changed page, score every candidate element against the saved dict and keep the highest
**iff it clears a `percentage` threshold (default 40)**:
- `tag` exact match → `+1`
- `text` → `SequenceMatcher` ratio
- `attributes` (and specifically `class`/`id`/`href`/`src`) → per-key ratios
- `path`, `siblings` → sequence matching
- parent `tag`/`attribs`/`text` → ratios
- final score = `(score / checks) * 100`, rounded 2dp; ties returned together.

`find_similar()` is a cheaper cousin: same tree depth + same tag + same parent hierarchy, then
filter by attribute `similarity_threshold` (default `0.2`).

A selector-generation mixin (`SelectorsGeneration._general_selection`) deliberately **refuses
class-based selectors** — _"some websites share exact classes"_ — preferring `id` shortcuts then
`nth-of-type` positional paths. (We independently hit the same trap; see our discrimination gate.)

## How ours differs — and why

| dimension | Scrapling | Yosoi page fingerprint |
|-----------|-----------|------------------------|
| **unit** | one ELEMENT | whole PAGE (`PageFingerprint`) |
| **key** | `(domain, identifier)` — domain in key | `(page_shape, region_role, field, type)` — **domain demoted to provenance** |
| **generalizes across domains?** | **No** — different domain ⇒ different row | **Yes** — same template on a mirror/locale/unseen domain shares atoms |
| **path primitive** | full root→element ancestor-tag tuple, per saved element | **set** of depth-D ancestor-tag paths (`page_skeleton`) aggregated over the whole page |
| **similarity** | weighted cumulative `SequenceMatcher` ratio | **Jaccard** set overlap per layer (skeleton L1, semantics L2) |
| **decision** | best candidate **above 40%** (recall-first) | **conjunctive fail-closed** — EVERY layer ≥ its threshold or refuse (precision-first) |
| **failure mode** | relocates to a plausible-but-wrong element | abstains → re-discover (a miss, never a wrong serve) |

**The key insight we take from Scrapling:** its per-element `path` (ancestor-tag tuple) is *exactly*
our skeleton shingle primitive — we just aggregate the **set** of those tuples over the whole page
instead of storing one per saved element. That cross-validates the skeleton design from an
independent, battle-tested codebase.

**The key thing we deliberately do NOT copy:** domain-in-the-key. Scrapling re-finds an element on
*the same site* after *that site's* redesign; it cannot reuse a discovery across `google.com` →
`google.co.uk`. Demoting domain to `domains_seen` provenance is the whole point of the field-atom
redesign — the web is the SSoT and the *template*, not the host, is the table identity.

**The trade we make consciously:** Scrapling optimizes **recall** (always relocate the element, even
on a 41%-similar page). We optimize **precision** (never serve a selector across a similar-but-not-equal
shape) because a wrong selector silently corrupts scrape output, whereas a miss just re-discovers —
cheap. That is why our matcher is conjunctive/fail-closed and Scrapling's is best-above-threshold.

See `experiments/fingerprint_generalization.py` for the live battery that validates these claims.

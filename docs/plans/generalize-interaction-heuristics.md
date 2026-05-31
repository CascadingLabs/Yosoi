# Plan: Replace hard-coded interaction heuristics with discovered actions

**Status:** proposed · **Origin:** hard-coded-selector audit (2026-05-30)
**Relates to:** `catalogues.py` FUTURE note (L6–7), `tree/actions.py` FUTURE note, CAS-92 (JS action discovery), CAS-84 (DOM preprocessing)

## Problem

The "Discover once, scrape forever" philosophy says an LLM discovers resilient
selectors per site, and AGENTS.md states **"We do not use fallback heuristics."**
The *selector discovery* path (`prompts/discovery.py`, `prompts/js_discovery.py`)
honours this. The **page-interaction path does not.**

`yosoi/core/fetcher/dom/catalogues.py` is a hand-maintained list of CSS
selectors and English text keywords that drive the behavior tree which renders a
page before/while extraction runs:

| Catalogue | Used by | What it hard-codes |
|---|---|---|
| `COOKIE_SELECTORS`, `POPUP_SELECTORS`, `AGE_GATE_SELECTORS` | `probes.py` obstacle detection, `tree/conditions.py` `HasOverlay`/`HasCloseButton`, `tree/actions.py` `ClickClose` | overlay/consent dismissal selectors |
| `LOAD_MORE_TEXTS`, `NEXT_PAGE_TEXTS` | `probes.py` trigger detection | English-only button/link label keywords |
| `PAGINATION_SELECTORS`, `ACCORDION_SELECTORS`, `TAB_SELECTOR` | `probes.py` | next-page / expand / tab selectors |
| `CONTENT_SELECTOR` | `loader.py`, `default.py` (`count_content`) | 10 hard-coded item class/tag names used to measure content growth |
| `CLICK_BY_TEXT_JS`, `CLICK_LINK_BY_TEXT_JS` | `tree/actions.py` | assumes clickables are `button, a[role=button], [type=button]` / `a[href]` |

### Why it's "held back"
- **English-only & convention-bound.** A localized "Mehr laden" / "Voir plus", a
  custom web-component button, or a `.product-box` container the list doesn't
  name simply isn't seen.
- **Triple duplication.** Overlay selectors are copied across `catalogues.py:25`,
  `tree/actions.py:48`, `tree/conditions.py:57` — drift-prone.
- **Acknowledged dead-ends.** `loader.py:104` notes count-growth over-clicks
  infinite feeds (X, Yahoo Finance); `catalogues.py:6` and `tree/actions.py`
  already flag these as future LLM-discovery targets.

### Why it can't just be deleted today
The stored recipe (`ActRecord` → `loader.replay`) persists only act **kinds +
cycle counts**, then *re-derives* the concrete trigger at replay time from the
same catalogue-driven probes. There is no per-site record of *which* selector to
click. Delete the catalogues and both the first-run probe and every replay lose
their targets. A replacement source of truth must land first.

## Goal

Move interaction targets from a global hand-list to a **per-domain discovered &
cached recipe**, mirroring the existing selector cache ("discover once, replay
forever"). The behavior-tree machinery (Selector/Sequence/Status, exhaustion
loops, DOM-stability settling) stays — only the *source of the selectors/labels*
changes from `catalogues.py` to a discovered `InteractionRecipe`.

## Proposed design

1. **`InteractionRecipe` model** (`models/` or extend `a3node.py`): per act kind,
   store the concrete discovered target — `{kind, target: Selector, label?}` —
   alongside the existing cycle count. Selectors reuse the existing `Selector`
   union (css / role / visual) already used by replay runtime.

2. **Interaction-discovery agent** (new `core/discovery/interaction_orchestrator.py`,
   modelled on `js_orchestrator.py`): given the rendered AX tree + DOM snapshot,
   the LLM proposes obstacle/trigger targets (cookie/consent, load-more,
   pagination, accordion, tab, infinite-scroll, content-item container). Verify
   each proposal live (does clicking it grow `count_content`? does dismissing it
   remove the overlay?) before persisting — same iterate-and-verify loop as CAS-92.

3. **Probes consume the recipe, not the catalogue.** `probes.py` /
   `conditions.py` / `actions.py` take an injected `recipe` (or fall back to the
   discovery agent on cold cache) instead of importing `catalogues`. The
   `count_content` selector becomes a discovered field too.

4. **Keep `catalogues.py` as the cold-start seed only.** Rename intent: it
   becomes the *prior* handed to the discovery agent ("here are common shapes")
   rather than the runtime source — exactly what `catalogues.py:6` already
   proposes. This is the safe-deletion endpoint: runtime code stops importing it.

5. **Dedup overlay selectors** (can ship independently, no behavior change):
   collapse the three copies into the single catalogue constant now, so the later
   migration has one site to change.

## Phasing

- **Phase 0 (safe now):** dedup the triple overlay selectors → `catalogues.py`.
- **Phase 1:** add `InteractionRecipe` + persistence; have `loader.run` write the
  *discovered* concrete target into the recipe (probes still use catalogue to
  find it the first time).
- **Phase 2:** add the interaction-discovery agent; `replay` uses the recipe's
  concrete targets directly (no re-probe).
- **Phase 3:** cold-run uses the agent (catalogue demoted to LLM prior); runtime
  imports of `catalogues.py` removed. Add a `max-items` contract primitive
  (`loader.py:104`) to bound infinite feeds.

## Out of scope / leave as-is
- Type-coercion lists (`price._ZERO_VALUE_WORDS`, `datetime._STRIP_PREFIXES`,
  `rating._WORD_MAP`, `url._TRACKING_PREFIXES`) — general-purpose parsing.
- `base.py` framework / bot-gate / RSS fingerprinting — standards-based fetch-tier
  signals, not selector discovery.
- `cleaning/cleaner.py` removals/thresholds — generic preprocessing (tunable
  later, separate concern).

## Already done
- **Bucket 1 (shipped):** de-vendored the `js_discovery.py` few-shot examples —
  removed Alita / Intercom / Drift / Zendesk / `$zopim` hardcoding that biased
  the JS-discovery LLM toward chat-widget/competitor use cases. Pure prompt text,
  no runtime change.

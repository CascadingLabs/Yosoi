# All SERP block types discriminated — better than naive (the goal)

`examples/serp_google/serp_blocks_round.py`, real discovery (Claude Agent SDK,
`claude-opus-4-7`) on one obfuscated Google SERP holding every block type.

## Result (real run, deterministically verified)

| block | rooted under | elements |
|-------|--------------|----------|
| ad (Sponsored) | `div.uEierd` | 2 |
| organic | `div.MjjYud` | 2 |
| AI overview | `div.YzCcne` | 2 |
| local pack / maps | `div.VkpGBb` | 4 |
| images | `div.img-brk …` | 1 |
| shopping | `.sh-dgr__content` | 2 |

- **YOSOI: `mutually_discriminated == True`** — all six contracts hit PAIRWISE-DISJOINT DOM
  regions. Each contract rooted its fields under its own block (field-level root + per-block
  intent docstrings + the prompt's root/intent guidance).
- **NAIVE hand-written selectors: `False`** — generic selectors (`a::attr(href)`, `#main a`,
  `img`, `h4`) collide: `ad↔organic`, `ad↔ai_overview`, `organic↔ai_overview` all overlap.
  Exactly the failure mode of `nimbal/core/web/_real.py`'s `#rso a h3` approach at scale.

So Yosoi beats naive scraping on the thing that actually matters at scale: telling the
blocks apart correctly, on obfuscated markup, without hand-tuning per site.

## Why it's trustworthy (the two tiers)

- **Tier 1 (deterministic, every discovery):** `discrimination.py` — region footprints
  (union of a contract's field elements via stable lxml `getpath`) must be pairwise disjoint
  and non-empty. No values, no prompts, no DOM-order luck. This is the gate that generalizes
  to a million pages and the honest PASS/FAIL.
- **Tier 2 (discriminator loop, `serp_blocks_round.discover_discriminated`):** when Tier 1
  reports an overlap, the offending contract is re-discovered with GROUNDED feedback (its
  intent + the selector that leaked + which block it leaked into) via the existing
  `FieldFeedback` retry, then re-gated. Bounded rounds; amortizes to ~0 (discovery is
  once-per-domain). On THIS run Tier 1 passed on round 0, so Tier 2 didn't need to fire —
  but it's the safety net for when prompting alone doesn't separate a block.

## Honest caveats

- Synthetic (but realistic, obfuscated) fixture, not live Google — the *mechanism* is what's
  proven: per-block rooting + deterministic region-disjointness + a re-discover loop. Live
  SERPs change the markup, not the approach.
- One model, one run; the model rooted every block correctly here. Tier 2 exists precisely
  because that won't always hold — and Tier 1 will catch it when it doesn't.

Run: `uv run --all-extras python examples/serp_google/serp_blocks_round.py`

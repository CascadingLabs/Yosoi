# Finding — real SERP discovery does NOT discriminate ad vs organic (W5, note #2)

Source: `examples/serp_google/serp_discovery_round.py`, first **real** round (Claude Agent
SDK / `claude-opus-4-7`) against a hard, obfuscated Google SERP fixture. No hardcoded
selectors — the discovery layer found these itself; parsel inline-verified them.

## What happened (real output, not asserted)

Two contracts that differ ONLY by docstring (`OrganicResult` vs `AdResult`):

```
OrganicResult.url   -> div.MjjYud div.yuRUbf > a::attr(href)
OrganicResult.title -> .MjjYud .yuRUbf h3.LC20lb
AdResult.url        -> div.MjjYud div.yuRUbf > a::attr(href)   # <-- SAME as organic
AdResult.title      -> .MjjYud .yuRUbf h3.LC20lb               # <-- SAME as organic
extracted organic: carebuildersathome.com/louisville/  (an ORGANIC result)
extracted ad:      carebuildersathome.com/louisville/  (WRONG — that is organic, not the Sponsored row)
```

`AdResult` was pointed at the organic `.MjjYud` block. The actual ad — the `.uEierd`
block with the `<span>Sponsored</span>` label and `premier-homecare-ads.example` href —
was ignored.

## Root cause — NOT what I first guessed

- It is **not** HTML cleaning: the cleaned HTML still contains the `Sponsored` label, the
  `uEierd` class, and the ad href (verified directly). Discovery saw the ad and skipped it.
- The system is **designed** to discriminate and the design is wired:
  - W5 signatures are distinct (`contract_signature` folds in the docstring) — distinct cache slots ✓
  - the contract docstring IS threaded into the discovery prompt (`orchestrator.py` `intent`) ✓
  - `prompts/discovery.py:_intent_block` even says verbatim: *"When several regions of the
    page expose the same fields (e.g. a sponsored/ad rail vs an organic results list), use
    this intent to choose the region that matches it — do NOT default to the first match."* ✓
- **The actual gap: two prompt instructions conflict, and the wrong one wins.**
  `prompts/discovery.py:76 _MULTI_ITEM_FIELD_GUIDANCE` tells each field agent to scope its
  selector "*inside a single repeating item*". The organic `.MjjYud` rows repeat 3×; the
  sponsored block is a **singleton**. So the repeating-item bias pulls every field toward
  the organic list and away from the lone ad — overriding the intent's region-selection
  instruction. Discovery is **field-first and region-blind**: each field (`url`, `title`)
  is discovered independently with a generic description (`"A URL"`, `"A title"`) and never
  first locates the intent's region.

## Why it matters

This is exactly Nimbal note #2 ("AdLink / OrganicLink contracts each have a URL and title,
the only differentiator is the docstring"). W5 made the **cache slots** distinct, but
discovery does not yet **act on** the intent to pick the ad region — so note #2 is only
half-solved: signatures distinct ✓, discrimination-in-practice ✗.

## Direction (make the system better)

1. **Region-first discovery when intent names a discriminator.** Before per-field fan-out,
   run an intent-scoped container pass: locate the region whose surrounding text/label
   matches the intent (e.g. has/【lacks】a "Sponsored"/"Ad" label), then scope all fields
   under that container. This makes intent win over the repeating-item bias by construction.
2. **Resolve the instruction conflict.** When an intent is present, `_MULTI_ITEM_FIELD_GUIDANCE`
   should defer to it — "scope within the *intent-matched* region, which may be a singleton",
   not "the repeating item". A singleton ad must not be discriminated against for being rare.
3. **Feed the label as a field-level cue.** The ad's only signal is the `Sponsored` label
   sibling; surface label/aria text near candidate regions into the prompt so the model can
   anchor on it.
4. **Caveat:** one round, one model (opus-4-7 via SDK). The *structural* conflict above is
   real regardless of model; re-run across models/fixtures to size how often it bites.

Repro: `uv run --all-extras python examples/serp_google/serp_discovery_round.py`
(defaults to the Claude Agent SDK transport — no API key needed).

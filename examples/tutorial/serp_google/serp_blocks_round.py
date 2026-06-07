"""All SERP block types, discriminated — the two-tier proof, vs naive scraping.

Goal: prove Yosoi correctly pulls AD, ORGANIC, AI OVERVIEW, LOCAL PACK (maps), IMAGES, and
SHOPPING off one obfuscated Google SERP — each to its own region — and that this beats
naive hand-written selectors.

How:
  * Tier 1 (deterministic, yosoi.core.discovery.discrimination): N contracts are correct iff
    their selectors hit PAIRWISE-DISJOINT DOM regions. No values, no prompts, no luck.
  * Tier 2 (discriminator loop, here): discover all blocks → Tier-1 gate → for any pair that
    overlaps, feed the offending contract GROUNDED feedback (its intent + the selector that
    leaked + which block it leaked into) and re-discover JUST it → re-gate. Bounded rounds.
    Discovery is once-per-domain, so the expensive loop amortizes to ~0 at replay.

Run (defaults to the Claude Agent SDK — no API key):
    uv run --all-extras python examples/tutorial/serp_google/serp_blocks_round.py
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from typing import Any

import yosoi as ys
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.discrimination import contract_element_ids, mutually_discriminated, overlapping_pairs
from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator
from yosoi.models.contract import Contract
from yosoi.prompts.discovery import FieldFeedback
from yosoi.storage.persistence import SelectorStorage

# --------------------------------------------------------------------------- #
# One obfuscated Google SERP with every block type. Each block is its own region
# with a distinguishing label; classes are Google-style soup, not semantic ids.
# --------------------------------------------------------------------------- #

SERP_HTML = """
<!doctype html><html><head><title>home care louisville - Google Search</title></head>
<body><div id="main"><div class="dURPMd">

  <div class="uEierd"><div class="CCgQ5"><span class="U3A9Ac">Sponsored</span></div>
    <a class="sVXRqc" href="https://premier-homecare-ads.example/lp?gclid=xyz">
      <h3 class="LC20lb">Premier Home Care of Louisville — Free Assessment</h3></a></div>

  <div class="YzCcne"><div class="hdzaWe"><span>AI Overview</span></div>
    <div class="LT6XE">Home care in Louisville ranges from companion care to skilled nursing.</div>
    <a class="aurc" href="https://kentuckyhomecare.example/guide"><span class="ZRkQfe">Kentucky Home Care Guide</span></a></div>

  <div class="VkpGBb"><div class="rllt__details"><span class="map-pin">Places</span>
    <div class="dbg0pd">CareBuilders at Home</div><span class="yi40Hd">4.8</span>
    <div class="dbg0pd">Senior Helpers</div><span class="yi40Hd">4.6</span></div></div>

  <div class="img-brk"><g-scrolling><span>Images</span>
    <a href="/imgres?q=home+care"><img class="rg_i" src="https://img.example/a.jpg" alt="caregiver helping senior"></a>
    <a href="/imgres?q=nurse"><img class="rg_i" src="https://img.example/b.jpg" alt="home nurse visit"></a></g-scrolling></div>

  <div class="sh-dgr__grid-result"><span class="shop-tag">Shopping</span>
    <div class="sh-dgr__content"><h4 class="A2sOrd">Home Care Starter Kit</h4><span class="a8Pemb">$129.00</span></div>
    <div class="sh-dgr__content"><h4 class="A2sOrd">Mobility Aid Bundle</h4><span class="a8Pemb">$249.99</span></div></div>

  <div class="MjjYud"><div class="yuRUbf"><a href="https://carebuildersathome.com/louisville/">
    <h3 class="LC20lb">CareBuilders at Home — Louisville, KY</h3></a></div></div>
  <div class="MjjYud"><div class="yuRUbf"><a href="https://www.homecare-aide.com/ky/louisville">
    <h3 class="LC20lb">Home Care Aide Services in Louisville</h3></a></div></div>

</div></div></body></html>
"""


# --------------------------------------------------------------------------- #
# A contract per block — distinguished by NL intent (the docstring).
# --------------------------------------------------------------------------- #


class AdResult(Contract):
    """A SPONSORED Google search ad — a paid result marked with a 'Sponsored'/'Ad' label, NOT organic."""

    url: str = ys.Url()
    title: str = ys.Title()


class OrganicResult(Contract):
    """An ORGANIC (unpaid) Google result — a regular blue-link result, NOT a sponsored ad, AI block, or widget."""

    url: str = ys.Url()
    title: str = ys.Title()


class AiOverviewSource(Contract):
    """A cited source link inside the AI OVERVIEW block (the AI-generated summary at the top), NOT an organic result."""

    url: str = ys.Url()
    title: str = ys.Title()


class LocalPackResult(Contract):
    """A business in the LOCAL PACK / Google Maps places widget — has a name and a star rating, NOT an organic link."""

    name: str = ys.Title()
    rating: str = ys.Rating()


class ImageResult(Contract):
    """A thumbnail in the IMAGES pack widget — an <img> with a src and alt text, NOT an organic result."""

    image_url: str = ys.Field(description='the image src URL of an image-pack thumbnail (img::attr(src))')
    alt: str = ys.Field(description="the image's alt text")


class ShoppingResult(Contract):
    """A product card in the SHOPPING / product-listing widget — has a product name and a price, NOT an organic result."""

    product: str = ys.Title()
    price: str = ys.Price()


BLOCKS: dict[str, type[Contract]] = {
    'ad': AdResult,
    'organic': OrganicResult,
    'ai_overview': AiOverviewSource,
    'local_pack': LocalPackResult,
    'images': ImageResult,
    'shopping': ShoppingResult,
}

# A naive scraper (what you'd hand-write fast): generic SERP selectors that conflate blocks.
NAIVE: dict[str, dict[str, Any]] = {
    'ad': {'url': {'primary': {'type': 'css', 'value': 'a::attr(href)'}}},
    'organic': {'url': {'primary': {'type': 'css', 'value': '#main a::attr(href)'}}},
    'ai_overview': {'url': {'primary': {'type': 'css', 'value': 'a::attr(href)'}}},
    'local_pack': {'name': {'primary': {'type': 'css', 'value': 'div'}}},
    'images': {'image_url': {'primary': {'type': 'css', 'value': 'img::attr(src)'}}},
    'shopping': {'product': {'primary': {'type': 'css', 'value': 'h4'}}},
}


def resolve_llm(model_arg: str | None) -> LLMConfig:
    from yosoi.core.discovery.config import claude_sdk

    if not model_arg or model_arg.startswith(('claude-sdk', 'claude_sdk')):
        _, _, name = model_arg.partition(':') if model_arg else ('', '', '')
        return claude_sdk(name or 'claude-opus-4-7')
    provider, _, name = model_arg.partition(':')
    return LLMConfig(provider=provider, model_name=name or '', api_key=None)


def _feedback_for(
    name: str, contract: type[Contract], my_map: dict[str, Any], leaked_into: list[str]
) -> dict[str, FieldFeedback]:
    """Grounded Tier-2 feedback: the contract leaked into another block's region."""
    intent = (contract.__doc__ or '').strip()
    others = ', '.join(leaked_into)
    fb: dict[str, FieldFeedback] = {}
    for field, slot in my_map.items():
        if field in ('root', 'container'):
            continue
        prev = ((slot.get('primary') or {}).get('value')) or ''
        fb[field] = FieldFeedback(
            message=(
                f'Your selector matched elements that belong to a DIFFERENT block ({others}). '
                f'This contract must target ONLY its own region. Intent: {intent} '
                f'Find the page region that matches THIS intent (look for its distinguishing label/structure) '
                f"and set this field's `root` to that block, then a simple leaf under it."
            ),
            failed_selectors=(prev,) if prev else (),
        )
    return fb


async def discover_discriminated(
    cfg: LLMConfig, *, rounds: int = 3
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], int]]:
    """Tier 2: discover every block, gate on Tier 1, re-discover overlappers with feedback."""
    lock = asyncio.Lock()
    with tempfile.TemporaryDirectory() as tmp:
        storage = SelectorStorage(storage_dir=f'{tmp}/selectors', content_dir=f'{tmp}/content')
        orchs = {n: DiscoveryOrchestrator(c, cfg, storage, write_lock=lock) for n, c in BLOCKS.items()}
        url = 'https://www.google.com/search?q=home+care+louisville'

        async def disc(n: str, fb: dict[str, FieldFeedback] | None = None) -> dict[str, Any]:
            return await orchs[n].discover_selectors(SERP_HTML, url=url, feedback=fb, force=fb is not None) or {}

        maps = dict(zip(BLOCKS, await asyncio.gather(*(disc(n) for n in BLOCKS)), strict=True))

        for _ in range(rounds):
            report = overlapping_pairs(SERP_HTML, maps)
            if not report:
                break
            offenders = sorted({n for pair in report for n in pair})
            leaks: dict[str, list[str]] = {n: [] for n in offenders}
            for a, b in report:
                leaks[a].append(b)
                leaks[b].append(a)
            redisc = await asyncio.gather(*(disc(n, _feedback_for(n, BLOCKS[n], maps[n], leaks[n])) for n in offenders))
            maps.update({n: m for n, m in zip(offenders, redisc, strict=True) if m})

        return maps, overlapping_pairs(SERP_HTML, maps)


async def _amain() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', help='provider:model_name (default: the Claude Agent SDK)')
    ap.add_argument('--rounds', type=int, default=3)
    a = ap.parse_args()

    # Baseline: naive hand-written selectors.
    naive_bad = overlapping_pairs(SERP_HTML, NAIVE)
    print('NAIVE hand-written selectors:')
    print(f'  mutually discriminated? {mutually_discriminated(SERP_HTML, NAIVE)}')
    print(f'  overlapping block pairs: {sorted(k for k in naive_bad)}\n')

    cfg = resolve_llm(a.model)
    print(f'YOSOI discovery + Tier-2 loop — model={cfg.provider}:{cfg.model_name}, {len(BLOCKS)} blocks\n')
    maps, remaining = await discover_discriminated(cfg, rounds=a.rounds)

    from parsel import Selector

    sel = Selector(text=SERP_HTML)
    for name, m in maps.items():
        footprint = len(contract_element_ids(sel, m))
        roots = {f: (s.get('root') or {}).get('value') for f, s in m.items() if isinstance(s.get('root'), dict)}
        print(f'  {name:12} elements={footprint}  roots={roots or "—"}')

    ok = mutually_discriminated(SERP_HTML, maps)
    print(f'\n  mutually discriminated? {ok}')
    if remaining:
        print(f'  still-overlapping pairs: {sorted(k for k in remaining)}')
    print(
        f'\nRESULT: {"PASS — all blocks hit disjoint regions; beats naive" if ok else "FINDING — Tier-2 did not fully separate (see overlaps)"}'
    )


def main() -> None:
    asyncio.run(_amain())


if __name__ == '__main__':
    main()

"""A full round of REAL SERP discovery against a hard, obfuscated Google SERP.

No hardcoded selectors, no scripted "brain": the actual Yosoi discovery layer (a real
LLM) must find resilient selectors for two contracts that differ ONLY by docstring,
then those selectors are inline-verified with parsel and used to extract the rows.

The environment is deliberately HARD — the way to make the system better is to make
the page harder, not to feed it answers:
  * No semantic ids (#rso / #tads are gone — modern Google is class-soup like
    ``MjjYud`` / ``yuRUbf`` / ``LC20lb``).
  * Organic and sponsored results share the SAME anchor+heading shape. The ONLY
    discriminator is a "Sponsored" label and surrounding structure — so discovery
    must use the contract INTENT (the docstring) to pick the right region, exactly
    what W5's docstring-threaded discovery is for.

The stress test: does discovery DISCRIMINATE organic from sponsored on obfuscated
markup, and do the discovered selectors verify + extract? Whatever it finds is the
real result — this script asserts nothing it hasn't actually discovered.

Run (needs a provider key in the environment, or pass --model):
    uv run --all-extras python examples/tutorial/serp_google/serp_discovery_round.py
    uv run --all-extras python examples/tutorial/serp_google/serp_discovery_round.py --model openai:gpt-4o
    uv run --all-extras python examples/tutorial/serp_google/serp_discovery_round.py --model ollama:llama3.1
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from typing import Any

import yosoi as ys
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator
from yosoi.core.extraction.extractor import ContentExtractor
from yosoi.models.contract import Contract
from yosoi.storage.persistence import SelectorStorage

# --------------------------------------------------------------------------- #
# HARD environment: obfuscated modern-Google class-soup. No #rso / #tads ids.
# Organic and sponsored rows share the same <a><h3> shape; the only ad signal is
# the "Sponsored" label + the container it sits in.
# --------------------------------------------------------------------------- #

HARD_SERP_HTML = """
<!doctype html><html><head><title>home care louisville - Google Search</title></head>
<body><div id="main"><div class="dURPMd">

  <div class="uEierd"><div class="v5yQqb">
    <div class="CCgQ5"><span class="U3A9Ac">Sponsored</span></div>
    <a class="sVXRqc" href="https://premier-homecare-ads.example/lp?gclid=xyz">
      <div class="VuuXrf">premier-homecare-ads.example</div>
      <h3 class="LC20lb MBeuO DKV0Md">Premier Home Care of Louisville — Free In-Home Assessment</h3>
    </a>
  </div>

  <div class="MjjYud"><div class="g"><div class="kb0PBd"><div class="yuRUbf">
    <a href="https://carebuildersathome.com/louisville/">
      <div class="VuuXrf">carebuildersathome.com</div>
      <h3 class="LC20lb MBeuO DKV0Md">CareBuilders at Home — Louisville, KY</h3>
    </a>
  </div></div></div></div>

  <div class="MjjYud"><div class="g"><div class="kb0PBd"><div class="yuRUbf">
    <a href="https://www.homecare-aide.com/ky/louisville">
      <div class="VuuXrf">homecare-aide.com</div>
      <h3 class="LC20lb MBeuO DKV0Md">Home Care Aide Services in Louisville</h3>
    </a>
  </div></div></div></div>

  <div class="MjjYud"><div class="g"><div class="kb0PBd"><div class="yuRUbf">
    <a href="https://seniorhelpers.com/ky/louisville/">
      <div class="VuuXrf">seniorhelpers.com</div>
      <h3 class="LC20lb MBeuO DKV0Md">Senior Helpers Louisville</h3>
    </a>
  </div></div></div></div>

</div></div></body></html>
"""


# --------------------------------------------------------------------------- #
# W5 — two redundant contracts that differ ONLY by docstring (the intent).
# No sentinels: the real LLM reads these semantically.
# --------------------------------------------------------------------------- #


class SerpResult(Contract):
    """A result row on a Google SERP: its link and visible title."""

    url: str = ys.Url()
    title: str = ys.Title()


OrganicResult = SerpResult.variant(
    'OrganicResultRound',
    'An organic (unpaid) Google result — one of the regular blue-link results in the '
    "main results column. NOT a sponsored ad: it has no 'Sponsored' or 'Ad' label.",
)
AdResult = SerpResult.variant(
    'AdResultRound',
    "A sponsored Google search ad — a paid result marked with a 'Sponsored' (or 'Ad') "
    'label, usually sitting above the organic results. NOT an organic result.',
)


# --------------------------------------------------------------------------- #
# Model resolution — a REAL provider from the env, or --model provider:name.
# --------------------------------------------------------------------------- #


def resolve_llm(model_arg: str | None) -> LLMConfig | None:
    """Return a real LLMConfig.

    Default: the Claude Agent SDK transport (``ys.claude_sdk``) — it uses the local
    Claude CLI subscription, so it needs no API key. ``--model env`` falls back to the
    first provider with a key in the environment; ``--model provider:name`` picks one
    explicitly (e.g. ``openai:gpt-4o``, ``ollama:llama3.1``).
    """
    from yosoi.core.discovery.config import claude_sdk

    if not model_arg or model_arg.startswith(('claude-sdk', 'claude_sdk')):
        _, _, name = model_arg.partition(':') if model_arg else ('', '', '')
        return claude_sdk(name or 'claude-opus-4-7')
    if model_arg == 'env':
        from yosoi.core.configs import find_available_provider

        found = find_available_provider()
        if not found:
            return None
        provider, name, key = found
        return LLMConfig(provider=provider, model_name=name, api_key=key)
    provider, _, name = model_arg.partition(':')
    return LLMConfig(provider=provider, model_name=name or '', api_key=None)


# --------------------------------------------------------------------------- #
# The round
# --------------------------------------------------------------------------- #


async def discover(contract: type[Contract], html: str, url: str, cfg: LLMConfig, storage: SelectorStorage):
    """Run one REAL discovery round for *contract* — no model override, no stub."""
    orch = DiscoveryOrchestrator(contract, cfg, storage)
    return await orch.discover_selectors(html, url=url)


def _primary(smap: dict[str, Any] | None, field: str) -> str:
    entry = (smap or {}).get(field) or {}
    leaf = ((entry.get('primary') or {}).get('value')) or '<none>'
    root = (entry.get('root') or {}).get('value') if isinstance(entry.get('root'), dict) else None
    return f'root={root!r} leaf={leaf!r}' if root else leaf


async def run_round(cfg: LLMConfig) -> dict[str, Any]:
    """Discover both contracts against the hard SERP, extract rows, return a report."""
    from yosoi.core.cleaning.cleaner import HTMLCleaner
    from yosoi.utils.signatures import contract_signature

    cleaned = HTMLCleaner().clean_html(HARD_SERP_HTML)
    url = 'https://www.google.com/search?q=home+care+louisville'

    with tempfile.TemporaryDirectory() as tmp:
        storage = SelectorStorage(storage_dir=f'{tmp}/selectors', content_dir=f'{tmp}/content')
        organic = await discover(OrganicResult, cleaned, url, cfg, storage)
        ad = await discover(AdResult, cleaned, url, cfg, storage)

    org_rows = (
        ContentExtractor(contract=OrganicResult).extract_content_with_html('', cleaned, organic) if organic else None
    )
    ad_rows = ContentExtractor(contract=AdResult).extract_content_with_html('', cleaned, ad) if ad else None

    from yosoi.core.discovery.dedup import maps_collide
    from yosoi.core.discovery.discrimination import discriminated as det_discriminated

    return {
        'collide': maps_collide(organic, ad),
        # TIER 1 (deterministic): do the two contracts resolve to DISJOINT DOM elements?
        # Independent of extracted values / DOM order — this is the honest gate.
        'discriminated': bool(organic) and bool(ad) and det_discriminated(cleaned, organic, ad),
        'organic_sig': contract_signature(OrganicResult),
        'ad_sig': contract_signature(AdResult),
        'organic_url_sel': _primary(organic, 'url'),
        'organic_title_sel': _primary(organic, 'title'),
        'ad_url_sel': _primary(ad, 'url'),
        'ad_title_sel': _primary(ad, 'title'),
        'organic_extracted': org_rows,
        'ad_extracted': ad_rows,
    }


async def _amain() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', help='provider:model_name, e.g. openai:gpt-4o or ollama:llama3.1')
    a = ap.parse_args()

    cfg = resolve_llm(a.model)
    if cfg is None:
        print('No LLM provider available. Real discovery needs a real model — this script')
        print('does NOT hardcode selectors. Set a provider key (e.g. OPENAI_API_KEY) in the')
        print('environment, or pass --model provider:name (e.g. --model ollama:llama3.1).')
        raise SystemExit(2)

    print(f'Real SERP discovery — model={cfg.provider}:{cfg.model_name}, hard obfuscated page\n')
    rep = await run_round(cfg)

    print(f'  signatures distinct? {rep["organic_sig"] != rep["ad_sig"]}')
    print('\n  DISCOVERED selectors (no hardcoding — the LLM found these, parsel-verified):')
    print(f'    OrganicResult.url   -> {rep["organic_url_sel"]}')
    print(f'    OrganicResult.title -> {rep["organic_title_sel"]}')
    print(f'    AdResult.url        -> {rep["ad_url_sel"]}')
    print(f'    AdResult.title      -> {rep["ad_title_sel"]}')
    print('\n  EXTRACTED via the discovered selectors:')
    print(f'    organic: {rep["organic_extracted"]}')
    print(f'    ad:      {rep["ad_extracted"]}')

    if rep['collide']:
        print('\n  ⚠ DEDUP SMELL: AdResult and OrganicResult resolved to IDENTICAL selectors —')
        print('    they are not being discriminated (one is wrong). The fix is field-level root:')
        print("    scope each contract's fields under its own region (Sponsored block vs organic list).")

    org = str((rep['organic_extracted'] or {}).get('url', ''))
    ad = str((rep['ad_extracted'] or {}).get('url', ''))
    discriminated = rep['discriminated']  # TIER 1 deterministic gate, NOT a value-diff guess
    print(f'\n  discriminated? {discriminated}  (deterministic: do the two selectors hit DISJOINT DOM elements?)')
    print(f'    organic url: {org or "<none>"}')
    print(f'    ad url:      {ad or "<none>"}')
    if not discriminated:
        print('    ↳ a contract whose selector overlaps the other region only extracted the right')
        print('      value by DOM-order luck — the value diff is NOT proof of discrimination.')
    print(
        f'\nRESULT: {"PASS — selectors hit disjoint regions (deterministically discriminated)" if discriminated else "FINDING — selectors overlap; not discriminated (Tier-1 gate failed)"}'
    )


def main() -> None:
    asyncio.run(_amain())


if __name__ == '__main__':
    main()

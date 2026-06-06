"""Nimbal's SERP-template use case, redone on Yosoi principles — and the issues at scale.

The original Nimbal flow (nimbal/core/web/_real.py + serp_template_queries.py):
  CSV of company locations  ->  render_matrix() per (company_type, city, state)  ->  Google
  search per query  ->  raw VoidCrawl + hand selectors  ->  presence/rank rollup.

Nimbal's serp_contracts.py was FORCED into ONE page-contract + a `sponsored` field because
"running several block-contracts against the SAME url ... the second pass clobbers the first"
— i.e. the W5 per-domain cache clobber. The spike LIFTS that: docstring-aware signatures +
field-level root + the Tier-1 discrimination gate let separate Ad/Organic/LocalPack contracts
coexist, and the new ``ys.scrape([urls], [contracts])`` 2x2 drives the whole grid.

This harness loads the real HubSpot CSV, renders the template queries, builds the Google
search URLs, and assembles the ``ys.scrape`` call. It is INSTRUMENTED to surface issues at
every stage (the point of the exercise). ``--live`` actually scrapes (and will hit the
anti-bot / fetcher issues we want to find); the default dry-run assembles + prints the scale.

Run:
    uv run --all-extras python examples/serp_google/nimbal_template_scrape.py --limit 3
    uv run --all-extras python examples/serp_google/nimbal_template_scrape.py --limit 1 --live
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

import yosoi as ys

NIMBAL = '/home/andrew/Desktop/Work/nimbal'
CSV_PATH = f'{NIMBAL}/data/hubspot-crm-exports-all-companies-2026-06-04-1.csv'
if NIMBAL not in sys.path:
    sys.path.insert(0, NIMBAL)


# --------------------------------------------------------------------------- #
# Yosoi SERP block contracts — separate contracts per block (now that W5 + root
# + discrimination make this safe; Nimbal had to collapse to one).
# --------------------------------------------------------------------------- #


class OrganicResult(ys.Contract):
    """An ORGANIC (unpaid) Google result — a regular blue-link result, NOT a sponsored ad or widget."""

    url: str = ys.Url()
    title: str = ys.Title()


class AdResult(ys.Contract):
    """A SPONSORED Google search ad — a paid result marked 'Sponsored'/'Ad', NOT an organic result."""

    url: str = ys.Url()
    title: str = ys.Title()


class LocalPackResult(ys.Contract):
    """A business in the LOCAL PACK / Google Maps places widget — a name + star rating, NOT an organic link."""

    name: str = ys.Title()
    rating: str = ys.Rating()


BLOCK_CONTRACTS = [OrganicResult, AdResult, LocalPackResult]


# --------------------------------------------------------------------------- #
# Stage 1 — load + parse the CSV into locations (instrumented).
# --------------------------------------------------------------------------- #


@dataclass
class Location:
    brand: str
    city: str
    state: str
    domain: str
    company_type: str = 'home_care'  # CareBuilders == home care; HubSpot has no type column yet


_STATE_RE = re.compile(r'\(([A-Z]{2})\)\s*$')


def load_locations(limit: int | None) -> tuple[list[Location], list[str]]:
    """Parse CSV rows -> Locations, collecting per-row ISSUES rather than failing."""
    locations: list[Location] = []
    issues: list[str] = []
    with open(CSV_PATH, newline='') as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            name = (row.get('Company name') or '').strip()
            city = (row.get('City') or '').strip()
            website = (row.get('Website URL') or '').strip()
            m = _STATE_RE.search(name)
            state = m.group(1) if m else ''
            brand = re.sub(r'\s*-\s*.*$', '', name).strip() or name  # strip " - <loc> (ST)"
            domain = urlparse(website).netloc.replace('www.', '') if website else ''
            if not city:
                issues.append(f'row {i}: no City for {name!r}')
            if not state:
                issues.append(f'row {i}: could not parse state from {name!r}')
            if not domain:
                issues.append(f'row {i}: no Website URL for {name!r}')
            locations.append(Location(brand=brand, city=city, state=state, domain=domain))
            if limit and len(locations) >= limit:
                break
    return locations, issues


# --------------------------------------------------------------------------- #
# Stage 2/3 — render template queries -> Google search URLs (instrumented).
# --------------------------------------------------------------------------- #


def search_url(query: str) -> str:
    return f'https://www.google.com/search?q={quote_plus(query)}&hl=en&gl=us'


def build_plan(locations: list[Location]) -> tuple[list[str], list[tuple[str, str, str]], list[str]]:
    """Return (unique search URLs, [(brand, intent, query)], issues)."""
    from nimbal.core.serp_template_queries import render_matrix

    rows: list[tuple[str, str, str]] = []
    urls: list[str] = []
    seen: set[str] = set()
    issues: list[str] = []
    for loc in locations:
        rendered = render_matrix(loc.company_type, brand=loc.brand, city=loc.city, state=loc.state)
        if not rendered:
            issues.append(f'{loc.brand} {loc.city}: render_matrix produced 0 queries')
        for rq in rendered:
            if rq.localization == 'teleport':
                # ISSUE seed: teleport queries drop the location words and expect a GPS spoof,
                # but ys.scrape has no teleport hook — a teleport query scraped without the spoof
                # returns NON-local results (wrong signal). Flagged, still counted.
                issues.append(
                    f'{loc.brand}: teleport query {rq.query!r} has no GPS spoof in ys.scrape (would be non-local)'
                )
            rows.append((loc.brand, rq.intent, rq.query))
            u = search_url(rq.query)
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls, rows, issues


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


async def _amain() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--limit', type=int, default=3, help='number of CSV companies to use')
    ap.add_argument('--live', action='store_true', help='actually run ys.scrape (will hit anti-bot issues)')
    ap.add_argument('--fetcher', default='simple', help='fetcher_type for --live (simple/headless/headful/waterfall)')
    ap.add_argument('--model', default='claude-sdk', help='discovery model for --live (default: keyless Claude SDK)')
    a = ap.parse_args()

    issues: list[str] = []

    locations, load_issues = load_locations(a.limit)
    issues += load_issues
    print(f'Stage 1 — loaded {len(locations)} locations from HubSpot CSV')
    for loc in locations:
        print(f'  {loc.brand} | {loc.city}, {loc.state or "??"} | {loc.domain or "??"}')

    urls, rows, plan_issues = build_plan(locations)
    issues += plan_issues
    print(f'\nStage 2/3 — {len(rows)} template queries -> {len(urls)} unique Google search URLs')
    print(f'  contracts/page: {[c.__name__ for c in BLOCK_CONTRACTS]}')
    print(
        f'  SCALE of the ys.scrape grid: {len(urls)} urls x {len(BLOCK_CONTRACTS)} contracts = {len(urls) * len(BLOCK_CONTRACTS)} (url,contract) units'
    )
    print(f'  example call: ys.scrape({urls[0]!r}..., [{", ".join(c.__name__ for c in BLOCK_CONTRACTS)}])')

    if a.live:
        print(f'\nStage 4 — LIVE ys.scrape (fetcher={a.fetcher}, model={a.model}); collecting issues...')
        model = ys.claude_sdk() if a.model.startswith(('claude-sdk', 'claude_sdk')) else a.model
        try:
            result = await ys.scrape(urls[:2], BLOCK_CONTRACTS, model=model, fetcher_type=a.fetcher, quiet=True)
            for u, by_contract in result.items():  # type: ignore[union-attr]
                print(f'\n  {u[:70]}')
                first_urls: dict[str, str] = {}
                for name, recs in by_contract.items():
                    if not recs:
                        print(f'    {name:16} -> 0 rows')
                        continue
                    rec = recs[0]
                    val = rec.get('url') or rec.get('name') or rec
                    first_urls[name] = str(val)
                    print(f'    {name:16} -> {len(recs)} row(s); first={val}')
                    if len(recs) <= 1:
                        issues.append(
                            f'live: {name} returned a SINGLE record — SERP blocks are LISTS; '
                            f'block contracts must be repeating (list[...]) to get all rows'
                        )
                if all(n == 0 for n in (len(r) for r in by_contract.values())):
                    issues.append(
                        f'live: {u[:50]} returned 0 rows for ALL contracts (likely blocked by {a.fetcher} fetcher)'
                    )
                # discrimination is NOT enforced by ys.scrape (Tier-1 gate is a FUTURE there):
                if len(set(first_urls.values())) < len(first_urls):
                    issues.append(
                        f'live: {u[:50]} — DIFFERENT block contracts extracted the SAME value '
                        f'({first_urls}); ys.scrape does not run the Tier-1 discrimination gate'
                    )
        except Exception as e:
            issues.append(f'live ys.scrape raised {type(e).__name__}: {e}')

    issues = list(dict.fromkeys(issues))  # dedup, preserve order
    print(f'\n=== ISSUES FOUND ({len(issues)}) ===')
    for n, issue in enumerate(issues, 1):
        print(f'  {n}. {issue}')
    if not issues:
        print('  (none at this stage)')


def main() -> None:
    asyncio.run(_amain())


if __name__ == '__main__':
    main()

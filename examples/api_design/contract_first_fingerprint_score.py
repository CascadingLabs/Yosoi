"""Contract-first fingerprint scoring: explain which page should reuse selectors.

Run:
    uv run python examples/api_design/contract_first_fingerprint_score.py

This is intentionally offline and figure-friendly: define the Contract first, choose
one known-good seed page for that Contract, then score new pages against the seed.
"""

from __future__ import annotations

from pydantic import Field

import yosoi as ys


class ProductCard(ys.Contract):
    """A product-listing card contract."""

    name: str = ys.Title(description='Product name shown on the card')
    price: float | None = ys.Price(description='Displayed product price')
    url: str = Field(description='Product detail URL')


SEED_CATALOG = """
<html><body><main class="catalog">
  <h1>Forge Catalog</h1>
  <section class="filters"><form><input name="q"><button>Search</button></form></section>
  <section class="grid">
    <article class="card"><h2>Hammer</h2><a href="/hammer">View</a><span>$10</span><img src="hammer.jpg"></article>
    <article class="card"><h2>Anvil</h2><a href="/anvil">View</a><span>$50</span><img src="anvil.jpg"></article>
  </section>
  <aside class="promo"><ul><li>Sale</li><li>Ships fast</li></ul></aside>
  <footer><nav><a href="/help">Help</a></nav></footer>
</main></body></html>
"""

SAME_CONTRACT_NEW_CONTENT = SEED_CATALOG.replace('Hammer', 'Tongs').replace('$10', '$12').replace('/hammer', '/tongs')

DIFFERENT_PAGE_SHAPE = """
<html><body><main class="article-page">
  <article>
    <header><h1>How to choose a hammer</h1><p>By Yosoi Guild</p></header>
    <section><p>Long-form prose body.</p><p>More prose and tips.</p></section>
    <section><h2>Related</h2><ul><li><a href="/story-2">Story 2</a></li></ul></section>
  </article>
  <footer><nav><a href="/archive">Archive</a></nav></footer>
</main></body></html>
"""


def score_candidate(label: str, seed_html: str, candidate_html: str) -> None:
    seed_fp = ys.fingerprint(seed_html)
    candidate_fp = ys.fingerprint(candidate_html)
    similarity = seed_fp.similarity(candidate_fp)

    print(f'{label}:')
    print(f'  contract:          {ProductCard.__name__}')
    print(f'  contract_fp:       {ProductCard.to_spec().fingerprint}')
    print(f'  page_score:        {similarity.score:.3f}  (0=different shape, 1=same shape)')
    print(f'  same_shape:        {similarity.same_shape}')
    print(f'  skeleton_score:    {similarity.skeleton:.3f}')
    print(f'  semantic_score:    {similarity.semantic:.3f}')
    print(f'  selector_reuse:    {"propose fingerprint-tier reuse" if similarity.same_shape else "do not reuse"}')
    print()


def main() -> None:
    print('Contract-first flow:')
    print('  ProductCard contract -> seed page fingerprint -> candidate page score -> reuse decision')
    print()

    score_candidate('Candidate A: another product catalog page', SEED_CATALOG, SAME_CONTRACT_NEW_CONTENT)
    score_candidate('Candidate B: article page, not a product catalog', SEED_CATALOG, DIFFERENT_PAGE_SHAPE)

    print('Figure caption: the Contract identity is stable, while page_score measures whether')
    print('a new page has the same structural environment as the seed page for that Contract.')


if __name__ == '__main__':
    main()

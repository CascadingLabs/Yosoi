"""Explore the high-level fingerprint score API.

Run:
    uv run python examples/api_design/fingerprint_score.py
"""

from __future__ import annotations

import yosoi as ys

CATALOG_A = """
<html><body><main class="catalog">
  <section class="hero"><h1>Forge Catalog</h1><p>Tools and supplies.</p></section>
  <section class="filters"><form><input name="q"><button>Search</button></form></section>
  <section class="grid">
    <article class="card"><h2>Hammer</h2><a href="/hammer">View</a><img src="hammer.jpg"></article>
    <article class="card"><h2>Anvil</h2><a href="/anvil">View</a><img src="anvil.jpg"></article>
  </section>
  <aside class="promo"><ul><li>Sale</li><li>Ships fast</li></ul></aside>
  <footer><nav><a href="/help">Help</a></nav></footer>
</main></body></html>
"""

CATALOG_B = CATALOG_A.replace('Hammer', 'Tongs').replace('/hammer', '/tongs')

ARTICLE = """
<html><body><main class="article-page">
  <article>
    <header><h1>How to season an anvil</h1><p>By Yosoi Guild</p></header>
    <section><p>Long-form article body with prose.</p><p>More prose.</p></section>
    <section><h2>Related</h2><ul><li><a href="/story-2">Story 2</a></li></ul></section>
  </article>
  <footer><nav><a href="/archive">Archive</a></nav></footer>
</main></body></html>
"""


def describe(label: str, left_html: str, right_html: str) -> None:
    left = ys.fingerprint(left_html)
    right = ys.fingerprint(right_html)
    similarity = left.similarity(right)

    print(f'\n{label}')
    print(f'  score:      {similarity.score:.3f}')
    print(f'  same_shape: {similarity.same_shape}')
    print(f'  skeleton:   {similarity.skeleton:.3f}')
    print(f'  semantic:   {similarity.semantic:.3f}')

    ys.show(left_html, fingerprint=right_html, title=label)


def main() -> None:
    describe('same catalog template, different content', CATALOG_A, CATALOG_B)
    describe('catalog vs article template', CATALOG_A, ARTICLE)


if __name__ == '__main__':
    main()

"""Tests for the one-pass static HTML pruning spike."""

from static_html_boss_fight import prune_static_html


def test_prune_static_html_keeps_main_article_content_and_removes_noise() -> None:
    """Keep article content while discarding non-content descendants."""
    source = """
    <html><body>
      <nav>navigation</nav>
      <main><h1>Web scraping</h1><script>alert(1)</script><p>Article body.</p><aside>aside</aside></main>
      <footer>footer</footer>
    </body></html>
    """

    pruned = prune_static_html(source)

    assert 'Web scraping' in pruned
    assert 'Article body.' in pruned
    assert 'navigation' not in pruned
    assert 'alert(1)' not in pruned
    assert 'aside' not in pruned

"""Static HTML fixture library — qscrape.dev L1 snapshots.

Fixtures are committed as plain HTML files in tests/fixtures/html/.
Refresh them by running:  uv run python scripts/download_fixtures.py
"""

from pathlib import Path

FIXTURES_HTML_DIR = Path(__file__).parent / 'html'


def load_html(name: str) -> str:
    """Load a fixture HTML file by name (e.g. 'mountainhome_home.html')."""
    path = FIXTURES_HTML_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Fixture '{name}' not found in {FIXTURES_HTML_DIR}. Run: uv run python scripts/download_fixtures.py"
        )
    return path.read_text(encoding='utf-8')


# Convenience names
MOUNTAINHOME_HOME = 'mountainhome_home.html'  # News portal homepage
MOUNTAINHOME_ARTICLES = 'mountainhome_articles.html'  # Article listing
VAULTMART_HOME = 'vaultmart_home.html'  # E-commerce homepage
VAULTMART_CATALOG = 'vaultmart_catalog.html'  # Product catalog
SCORETAP_HOME = 'scoretap_home.html'  # Esports scores
ELDORIA_REGISTRY = 'eldoria_registry.html'  # Structured form/table data

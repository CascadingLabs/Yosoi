import pytest
from bs4 import BeautifulSoup
from yosoi.cleaner import HTMLCleaner


@pytest.fixture
def sample_html():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <script>console.log('noisy script');</script>
        <style>.ads { color: red; }</style>
    </head>
    <body>
        <nav>
            <ul>
                <li><a href="/">Home</a></li>
            </ul>
        </nav>
        <header>
            <h1>My Website</h1>
        </header>
        <main id="content">
            <article>
                <h2 class="headline">Main Story</h2>
                <p>This is the important content.</p>
                <div class="ad-banner">Buy things!</div>
            </article>
            <aside class="sidebar">
                <h3>Links</h3>
                <ul>
                    <li><a href="#">Link 1</a></li>
                </ul>
            </aside>
        </main>
        <footer>
            <p>&copy; 2025</p>
        </footer>
    </body>
    </html>
    """


def test_clean_html_removes_noise(sample_html):
    """Test that HTMLCleaner removes scripts, styles, nav, header, and footer."""
    cleaner = HTMLCleaner()
    clean_html = cleaner.clean_html(sample_html)
    soup = BeautifulSoup(clean_html, 'html.parser')

    # Verify noise removal
    assert soup.find('script') is None
    assert soup.find('style') is None
    assert soup.find('nav') is None
    assert soup.find('header') is None
    assert soup.find('footer') is None

    # Verify content remains
    assert soup.find('h2', class_='headline') is not None
    assert 'Main Story' in clean_html
    assert 'This is the important content.' in clean_html


def test_clean_html_removes_sidebars(sample_html):
    """Test that HTMLCleaner removes sidebar elements."""
    cleaner = HTMLCleaner()
    clean_html = cleaner.clean_html(sample_html)
    soup = BeautifulSoup(clean_html, 'html.parser')

    # Verify sidebar removal (sidebars are always removed in clean_html)
    assert soup.find('aside', class_='sidebar') is None
    # Note: The word "Links" might still appear if it's in the main content


def test_clean_html_fallback_to_main():
    """Test that HTMLCleaner extracts main content when available."""
    html = '<html><head></head><body><main><h1>Only Main</h1></main></body></html>'
    cleaner = HTMLCleaner()
    clean_html = cleaner.clean_html(html)

    assert 'Only Main' in clean_html

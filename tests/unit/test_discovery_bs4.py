import pytest
from bs4 import BeautifulSoup

from yosoi.discovery import SelectorDiscovery


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


def test_extract_content_html_removes_noise(sample_html, mocker):
    discovery = SelectorDiscovery(llm_config=None, agent=mocker.Mock())
    # We need to bypass the llm_config check in __init__ for unit testing the extraction method
    discovery.remove_sidebars = False

    clean_html = discovery._extract_content_html(sample_html)
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


def test_extract_content_html_removes_sidebars(sample_html, mocker):
    # Mocking the Agent dependency
    from pydantic_ai import Agent

    mock_agent = mocker.Mock(spec=Agent)
    discovery = SelectorDiscovery(agent=mock_agent, remove_sidebars=True)

    clean_html = discovery._extract_content_html(sample_html)
    soup = BeautifulSoup(clean_html, 'html.parser')

    # Verify sidebar removal
    assert soup.find('aside', class_='sidebar') is None
    assert 'Links' not in clean_html


def test_extract_content_html_fallback_to_main(mocker):
    html = '<html><head></head><body><main><h1>Only Main</h1></main></body></html>'
    # Using a fake agent to avoid LLM initialization
    mock_agent = mocker.Mock()
    discovery = SelectorDiscovery(agent=mock_agent)

    clean_html = discovery._extract_content_html(html)
    assert 'Only Main' in clean_html
    assert '<body>' not in clean_html  # Since it returns the content string

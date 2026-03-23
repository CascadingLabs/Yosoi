"""Extract main content region from the HTML tree."""

from bs4 import BeautifulSoup, Tag


def extract_content(soup: BeautifulSoup) -> tuple[BeautifulSoup, str]:
    """Locate the main content region and return it as a new soup.

    Tries ``<main>`` inside ``<body>``, then ``<body>``, then top-level
    ``<main>``, and finally falls back to the entire document.

    Args:
        soup: Parsed HTML tree (already noise-stripped).

    Returns:
        A tuple of (new BeautifulSoup from the content region, extraction method label).

    """
    body = soup.find('body')
    content = None
    method = ''

    if body and isinstance(body, Tag):
        main_in_body = body.find('main')
        if main_in_body and isinstance(main_in_body, Tag):
            content = main_in_body
            method = '<main> inside <body>'
        else:
            content = body
            method = '<body>'
    else:
        main = soup.find('main')
        if main and isinstance(main, Tag):
            body_in_main = main.find('body')
            if body_in_main and isinstance(body_in_main, Tag):
                content = body_in_main
                method = '<body> inside <main>'
            else:
                content = main
                method = '<main>'
        else:
            content = soup
            method = 'full HTML'

    return BeautifulSoup(str(content), 'lxml'), method

"""
SIMPLE APPROACH: AI Reads HTML and Returns Selectors
=====================================================

Instead of complicated text matching, just ask AI to read the HTML
and tell us where things are!
"""

import json
import os

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# LLM Configuration
llm_model = ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    google_api_key=os.getenv('GEMINI_KEY'),
    temperature=0,
)


def get_selectors_from_ai(url: str, html: str) -> dict | None:
    """Ask AI to find CSS selectors by reading the HTML."""

    # Extract just the relevant parts of HTML
    soup = BeautifulSoup(html, 'html.parser')

    # Remove script, style, svg tags (noise)
    for tag in soup.find_all(['script', 'style', 'svg', 'path']):
        tag.decompose()

    # Try to find the main content area
    main_content = None
    for selector in ['article', 'main', '[role="main"]', '.post', '.entry', 'content', '#content']:
        main_content = soup.select_one(selector)
        if main_content:
            break

    # Use main content if found, otherwise use body
    if main_content:
        html_to_analyze = str(main_content)[:30000]  # First 30k chars of main content
        print(f'  → Extracted {len(html_to_analyze)} chars from <{main_content.name}> tag')
    else:
        # Fall back to body
        body = soup.find('body')
        if body:
            html_to_analyze = str(body)[:30000]
            print(f'  → Extracted {len(html_to_analyze)} chars from <body> tag')
        else:
            html_to_analyze = str(soup)[:30000]
            print(f'  → Using first {len(html_to_analyze)} chars of HTML')

    prompt = f"""You are analyzing HTML to find CSS selectors for web scraping.

CRITICAL: Look at the ACTUAL class names, IDs, and attributes in the HTML below. Do NOT guess or make up common class names like "entry-title" or "post-content" unless they actually appear in this HTML.

Here is the HTML from {url}:

```html
{html_to_analyze}
```

Find CSS selectors for these fields by READING THE ACTUAL HTML ABOVE:

1. **headline** - Main article headline (look for h1, h2 with article-related classes)
2. **author** - Author name (look for links with "author" in href, or elements with author/byline classes)
3. **date** - Publication date (look for <time> tags or elements with date/published classes)
4. **body_text** - Article body paragraphs (look for <p> tags inside article/content containers)
5. **related_content** - Related article links (look in aside, sidebar, or related sections)

RULES:
1. ONLY use class names and IDs that ACTUALLY APPEAR in the HTML above
2. Look for semantic HTML5 tags: <article>, <time>, <aside>
3. Look for links with "author" in href attribute
4. For body_text, find the container with the most <p> tags
5. If a field doesn't exist, return "NA" for all three

Return THREE selectors per field (in order of preference):
- **primary**: Most specific (using actual classes/IDs you see in the HTML)
- **fallback**: Less specific but still reliable
- **tertiary**: Generic fallback (just tag name)

Example format (using ACTUAL classes from the HTML):
{{
  "headline": {{
    "primary": "h1.actual-class-name",
    "fallback": "h1[some-actual-attribute]",
    "tertiary": "h1"
  }},
  "author": {{
    "primary": "a[href*='author']",
    "fallback": "NA",
    "tertiary": "NA"
  }},
  ...
}}

Return ONLY valid JSON, no markdown, no explanations."""

    try:
        response = llm_model.invoke(prompt)
        result_text = response.content

        # Clean up response
        result_text = result_text.strip()
        if result_text.startswith('```json'):
            result_text = result_text[7:]
        if result_text.startswith('```'):
            result_text = result_text[3:]
        if result_text.endswith('```'):
            result_text = result_text[:-3]
        result_text = result_text.strip()

        # Parse JSON
        selectors = json.loads(result_text)
        return selectors

    except Exception as e:
        print(f'  ✗ Error getting selectors from AI: {e}')
        return None


def validate_selectors(url: str, selectors: dict) -> dict:
    """Test each selector to see if it finds elements."""

    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        validated = {}

        for field, field_selectors in selectors.items():
            print(f'\n  Testing {field}:')

            best_selector = None
            best_priority = None

            # Try primary, fallback, tertiary in order
            for priority in ['primary', 'fallback', 'tertiary']:
                selector = field_selectors.get(priority)

                if not selector or selector == 'NA':
                    print(f'    {priority}: NA')
                    continue

                try:
                    # Test if selector finds elements
                    if field == 'body_text':
                        elements = soup.select(selector)
                    else:
                        elements = [soup.select_one(selector)] if soup.select_one(selector) else []

                    if elements and any(el and el.get_text(strip=True) for el in elements):
                        sample_text = elements[0].get_text(strip=True)[:60]
                        print(f'    ✓ {priority}: \'{selector}\' → "{sample_text}..."')

                        # Keep first working selector
                        if not best_selector:
                            best_selector = selector
                            best_priority = priority
                    else:
                        print(f"    ✗ {priority}: '{selector}' (no elements found)")

                except Exception as e:
                    print(f"    ✗ {priority}: '{selector}' (error: {e})")

            # Store the best working selector
            if best_selector:
                validated[field] = {
                    'primary': best_selector,
                    'fallback': field_selectors.get('fallback'),
                    'tertiary': field_selectors.get('tertiary'),
                    'working_priority': best_priority,
                }
                print(f"  → Using {best_priority} selector: '{best_selector}'")
            else:
                print(f'  → No working selectors for {field}')

        return validated

    except Exception as e:
        print(f'  ✗ Validation error: {e}')
        return {}


def discover_selectors(url: str) -> dict:
    """Complete workflow: Fetch HTML → AI finds selectors → Validate them."""

    print(f'\nDiscovering selectors for: {url}')
    print('=' * 80)

    # Step 1: Fetch HTML
    print('\nStep 1: Fetching HTML...')
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        html = response.text
        print(f'✓ Fetched {len(html)} characters of HTML')
    except Exception as e:
        print(f'✗ Failed to fetch page: {e}')
        return {}

    # Step 2: Ask AI to find selectors by reading HTML
    print('\nStep 2: AI analyzing HTML to find selectors...')
    selectors = get_selectors_from_ai(url, html)

    if not selectors:
        print('✗ AI failed to find selectors, using fallback heuristics')
        selectors = get_fallback_selectors()

    # Check if AI gave up (all NA)
    all_na = all(all(v == 'NA' for v in field_sel.values()) for field_sel in selectors.values())

    if all_na:
        print('⚠ AI returned all NA, using fallback heuristics')
        selectors = get_fallback_selectors()

    print('✓ AI found selectors:')
    print(json.dumps(selectors, indent=2))

    # Step 3: Validate selectors actually work
    print('\nStep 3: Validating selectors on actual page...')
    validated = validate_selectors(url, selectors)

    if validated:
        print(f'\n✓ Successfully discovered {len(validated)} working field selectors')
    else:
        print('\n✗ No working selectors found')

    return validated


def get_fallback_selectors() -> dict:
    """Return generic heuristic selectors when AI fails."""
    return {
        'headline': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'h3'},
        'author': {'primary': "a[href*='author']", 'fallback': '.author', 'tertiary': '.byline'},
        'date': {'primary': 'time', 'fallback': '.published', 'tertiary': '.date'},
        'body_text': {'primary': 'article p', 'fallback': '.content p', 'tertiary': 'p'},
        'related_content': {'primary': 'aside a', 'fallback': '.related a', 'tertiary': '.sidebar a'},
    }


def save_selectors(domain: str, selectors: dict):
    """Save selectors to JSON file."""
    os.makedirs('selectors', exist_ok=True)

    safe_domain = domain.replace('.', '_').replace('/', '_')
    filepath = f'selectors/selectors_{safe_domain}.json'

    data = {
        'domain': domain,
        'selectors': selectors,
        'version': '3.0',  # New AI-reads-HTML approach
        'created': '2024-12-22',
    }

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    print(f'\n✓ Saved to {filepath}')


# ============================================================================
# Test it
# ============================================================================

if __name__ == '__main__':
    urls = [
        'https://virginiabusiness.com/new-documents-reveal-scope-of-googles-chesterfield-data-center-campus/',
        'https://finance.yahoo.com/video/three-big-questions-left-musk-125600891.html',
    ]

    for url in urls:
        # Extract domain
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.replace('www.', '')

        # Discover selectors
        selectors = discover_selectors(url)

        # Save if we found any
        if selectors:
            save_selectors(domain, selectors)

        print('\n' + '=' * 80 + '\n')

Analyze this HTML and find selectors for web scraping.

Here is the HTML from {url}:
```html
{html}
```

Find CSS/HTML/JS selectors for these fields:

**headline** - Main article title (h1/h2 in article, NOT navigation)
**author** - Author name (author/byline classes or links)
**date** - Publication date (time tags or date/published classes)
**body_text** - Article paragraphs (p tags in article, NOT sidebars/ads)
**related_content** - Related article links (aside/sidebar sections)

For each field provide three selectors:
- primary: Most specific selector using actual classes/IDs from the HTML
- fallback: Less specific but reliable selector
- tertiary: Generic selector or null if field doesn't exist

IMPORTANT: Only use selectors that actually exist in the HTML above.

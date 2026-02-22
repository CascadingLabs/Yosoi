[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18713573.svg)](https://doi.org/10.5281/zenodo.18713573)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Actions status](https://github.com/CascadingLabs/Yosoi/actions/workflows/CI.yaml/badge.svg)](https://github.com/CascadingLabs/Yosoi/actions)
[![image](https://img.shields.io/pypi/pyversions/yosoi.svg)](https://pypi.python.org/pypi/yosoi)
[![image](https://img.shields.io/pypi/v/yosoi.svg)](https://pypi.python.org/pypi/yosoi)
<!-- [![image](https://img.shields.io/pypi/l/yosoi.svg)](https://pypi.python.org/pypi/yosoi) -->

# Yosoi - AI-Powered CSS Selector Discover

> **Discover CSS selectors once with AI, scrape forever with BeautifulSoup**

Give Yosoi a URL, and it uses AI to automatically discover the best CSS selectors for extracting headlines, authors, dates, body text, and related content. Discovery takes 3 seconds and costs $0.001 per domain — then scrape thousands of articles for free with BeautifulSoup.

**Key Benefits:**
- **Fast**: 3 seconds to discover selectors per domain
- **Cheap**: $0.001 per domain (one-time cost)
- **Accurate**: Validates selectors before saving
- **Reusable**: Discover once, use forever
- **Production-Ready**: Type-safe, linted, tested

## Quick Start

### Installation

```bash
# Clone the repository
git clone <your-repo>
cd yosoi

# Install dependencies (using uv)
uv sync

# For development tools
uv sync --group dev
```

### Configuration

Create a `.env` file (see `env.example`):

```bash
# Choose one or both providers
GROQ_KEY=your_groq_api_key_here           # For Llama 3.3 (faster, recommended)
GEMINI_KEY=your_gemini_api_key_here       # For Gemini 2.0 Flash

# Optional: Observability
LOGFIRE_TOKEN=your_logfire_token_here     # For Logfire tracing
```

**Get API Keys:**
- Groq (Free): https://console.groq.com/keys
- Gemini: https://aistudio.google.com/app/apikey
- Logfire (Optional): https://logfire.pydantic.dev

### Basic Usage

```bash
# Process a single URL
uv run yosoi --url https://example.com/article

# Process multiple URLs from a file
uv run yosoi --file urls.txt

# Force re-discovery
uv run yosoi --url https://example.com --force

# Show summary of all saved selectors
uv run yosoi --summary

# Enable debug mode (saves extracted HTML)
uv run yosoi --url https://example.com --debug
```

### URLs File Format

Create `urls.txt` with one URL per line:

```text
https://example.com/article1
https://example.com/article2
# Comments are allowed
https://example.com/article3
```

Or use JSON format (`urls.json`):

```json
[
  {"url": "https://example.com/article1"},
  {"url": "https://example.com/article2"}
]
```

## Project Structure

```
.
├── .yosoi/                        # Hidden runtime directory
│   └── selectors/                 # Persisted selector snapshots
├── yosoi/                         # Main package
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                     # CLI entry point & argument parsing
│   ├── core/                      # Core pipeline logic
│   │   ├── pipeline.py            # SelectorDiscoveryPipeline orchestrator
│   │   ├── cleaning/
│   │   │   └── cleaner.py         # HTML noise removal
│   │   ├── discovery/
│   │   │   ├── agent.py           # pydantic-ai agent definition
│   │   │   └── config.py          # Model / provider configuration
│   │   ├── extraction/
│   │   │   └── extractor.py       # Relevant HTML extraction
│   │   ├── fetcher/
│   │   │   ├── base.py            # Abstract fetcher interface
│   │   │   ├── simple.py          # httpx-based fetcher
│   │   │   ├── playwright.py      # Playwright fetcher (JS-heavy sites)
│   │   │   └── smart.py           # Auto-selects fetcher strategy
│   │   └── verification/
│   │       └── verifier.py        # CSS selector verification
│   ├── models/                    # Pydantic data models
│   │   ├── selectors.py           # SelectorSet & field models
│   │   └── results.py             # Pipeline result types
│   ├── storage/                   # Persistence layer
│   │   ├── persistence.py         # JSON read/write for selectors
│   │   ├── tracking.py            # Domain-level tracking & stats
│   │   └── debug.py               # Debug HTML snapshot storage
│   ├── outputs/                   # Output formatters
│   │   ├── json.py                # JSON report formatter
│   │   ├── markdown.py            # Markdown / Rich table output
│   │   └── utils.py               # Shared output helpers
│   ├── prompts/                   # LLM prompt templates (markdown)
│   │   ├── discovery_system.md
│   │   └── discovery_user.md
│   └── utils/                     # Shared utilities
│       ├── exceptions.py          # Custom exception hierarchy
│       ├── files.py               # File-path helpers
│       ├── headers.py             # HTTP header rotation
│       ├── logging.py             # Structured logging setup
│       ├── prompts.py             # Prompt loader utility
│       └── retry.py               # Retry / back-off helpers
├── tests/
│   ├── conftest.py
│   ├── integration/
│   │   ├── test_pipeline.py       # End-to-end pipeline tests
│   │   └── test_snapshots.py      # Selector snapshot regression tests
│   └── unit/
│       ├── test_discovery_bs4.py
│       ├── test_pipeline.py
│       └── test_pydantic_flow.py
├── pyproject.toml                 # Project config & dependencies
├── env.example                    # API key template
└── urls.txt                       # Example URL list
```

## How It Works

### Phase 1: Smart HTML Extraction
```
Full HTML (2MB)
  ↓
Remove noise (scripts, styles, nav, footer)
  ↓
Find main content (<article>, <main>, .content)
  ↓
Extract ~30k chars of relevant HTML
  ↓
Send to AI
```

### Phase 2: AI Analysis
```
AI reads actual HTML structure
  ↓
Finds real class names & IDs
  ↓
Returns up to 3 selectors per field:
  - Primary (most specific)
  - Fallback (reliable backup)
  - Tertiary (generic)
```

### Phase 3: Validation
```
Test each selector on the actual page
  ↓
Find first working selector per field
  ↓
Mark which priority worked (primary/fallback/tertiary)
  ↓
Save validated selectors to JSON
```

## Output Format

Selectors are saved as JSON files in the `.yosoi/selectors/` directory:

```json
{
  "headline": {
    "primary": "h1.article-title",
    "fallback": "h1",
    "tertiary": "h2"
  },
  "author": {
    "primary": "a[href*='/author/']",
    "fallback": ".byline",
    "tertiary": "NA"
  },
  "date": {
    "primary": "time.published-date",
    "fallback": "time",
    "tertiary": ".date"
  },
  "body_text": {
    "primary": "article.content p",
    "fallback": "article p",
    "tertiary": "p"
  },
  "related_content": {
    "primary": "aside.related a",
    "fallback": ".sidebar a",
    "tertiary": "NA"
  }
}
```

## Using Discovered Selectors

Once selectors are discovered, use them with standard BeautifulSoup:

```python
from yosoi.storage.persistence import SelectorStorage
from bs4 import BeautifulSoup
import requests

# Load discovered selectors
storage = SelectorStorage()
selectors = storage.load_selectors('example.com')

# Scrape using the selectors (fast & free!)
url = 'https://example.com/another-article'
html = requests.get(url).text
soup = BeautifulSoup(html, 'html.parser')

# Extract data using validated selectors
headline_selector = selectors['headline']['primary']
headline = soup.select_one(headline_selector)
if headline:
    print(f"Headline: {headline.get_text(strip=True)}")

# Extract body text
body_selector = selectors['body_text']['primary']
paragraphs = soup.select(body_selector)
body_text = '\n\n'.join(p.get_text(strip=True) for p in paragraphs)
print(f"\nBody:\n{body_text}")
```

### Using as a Library

```python
from yosoi.core.pipeline import SelectorDiscoveryPipeline
import os

# Initialize with your preferred provider
pipeline = SelectorDiscoveryPipeline(
    ai_api_key=os.getenv('GROQ_KEY'),
    model_name='llama-3.3-70b-versatile',
    provider='groq'
)

# Process a URL
success = pipeline.process_url('https://example.com/article')

# Process multiple URLs
urls = ['https://example.com/article1', 'https://example.com/article2']
pipeline.process_urls(urls, force=False)

# Show summary
pipeline.show_summary()
```

## Supported AI Models

### Groq (Recommended)
- **Model**: `llama-3.3-70b-versatile`
- **Cost**: Free tier available
- **Setup**: `GROQ_KEY` in `.env`

### Google Gemini
- **Model**: `gemini-2.0-flash`
- **Cost**: Free tier available
- **Setup**: `GEMINI_KEY` in `.env`

The system automatically uses Groq if `GROQ_KEY` is set, otherwise falls back to Gemini.

## Observability with Logfire

Yosoi integrates with [Logfire](https://logfire.pydantic.dev) for comprehensive observability:

**What's Tracked:**
- Request/response traces for each URL
- AI model calls and responses
- Selector validation results
- Performance metrics
- Error tracking

**Enable Logfire:**
1. Sign up at https://logfire.pydantic.dev
2. Get your token
3. Add `LOGFIRE_TOKEN=your_token` to `.env`
4. Run your discovery process
5. View traces in Logfire dashboard

## Features

**AI-Powered** - Uses Groq/Gemini to read HTML and find selectors
**Cheap** - $0.001 per domain
**Verified** - Tests each selector on the live page before saving
**Organized** - Clean JSON output per domain
**Rich CLI** - Nice terminal output with progress indicators
**Type-Safe** - Full type hints with mypy checking
**Observable** - Integrated with Logfire for tracing
**Production-Ready** - Linted, formatted, and tested

## Troubleshooting

### AI Returns All "NA"
**Cause**: Site has poor semantic HTML or heavy JavaScript rendering
**Solution**:
- Check if site requires JavaScript (use debug mode: `--debug`)
- Review extracted HTML in `debug_html/` directory
- Use the Playwright fetcher for JavaScript-heavy sites (`SmartFetcher` selects it automatically)
- If the site explicitly fails, re-run with `--force` after verifying the page loads in a browser

### Selectors Don't Work
**Cause**: Site structure changed or uses dynamic content
**Solution**:
- Re-run with `--force` to re-discover selectors
- Check if site requires authentication
- Verify selectors with `--debug` mode

### API Key Errors
**Problem**: `GROQ_KEY` or `GEMINI_KEY` not found
**Solution**:
- Ensure `.env` file exists in project root
- Verify key is correctly formatted (no quotes needed)
- Check key has not expired at provider's dashboard

### HTTP Errors (403, 429, 500)
- **403 Forbidden**: Site blocks scrapers - may need different User-Agent
- **429 Too Many Requests**: Rate limited - add delays between requests
- **5xx Server Error**: Server issue - Yosoi will skip retries automatically

### Import Errors
**Problem**: `ModuleNotFoundError` for pydantic_ai, logfire, etc.
**Solution**:
```bash
# Reinstall dependencies
uv sync

# If still failing, try clean install
rm -rf .venv
uv sync
```

## Best Practices

### For Reliable Scraping

1. **Test on multiple pages**: Validate selectors work across different articles
2. **Use fallback selectors**: Always have primary/fallback/tertiary
3. **Monitor changes**: Re-discover periodically (sites change)
4. **Handle missing data**: Not all fields exist on all pages

### For Better AI Results

1. **Use debug mode first**: Check what HTML is being sent to AI
2. **Prefer semantic HTML**: Sites with `<article>`, `<time>`, etc. work best
3. **Avoid paywalled sites**: Content behind login walls won't work
4. **Check rate limits**: Respect site's `robots.txt` and rate limits

### For Production Use

1. **Cache selectors**: Store and reuse for same domain
2. **Add error handling**: Sites can change or go down
3. **Use Logfire**: Monitor success rates and failures
4. **Set timeouts**: Don't let requests hang indefinitely

## Limitations / Future Developments

- **JavaScript-rendered content**: Not visible in raw HTML (maybe a future development)
- **Paywalled sites**: Cannot access content behind logins
- **Dynamic selectors**: Sites that change class names frequently
- **Rate limits**: Some sites may block or rate-limit requests

## Citation

If you use **yosoi** in your research or project, please cite it using the metadata provided in the `CITATION.cff` file.

### BibTeX
If you are using LaTeX, you can use the following entry:

```bibtex
@software{Berg_yosoi_2026,
author = {Berg, Andrew and Miles, Houston and Mefford, Braeden and Wang, Mia},
license = {Apache-2.0},
month = feb,
title = {{yosoi}},
url = {https://github.com/CascadingLabs/Yosoi},
version = {0.0.1-alpha6},
year = {2026}
}
```

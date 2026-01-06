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
uv run main.py --url https://example.com/article

# Process multiple URLs from a file
uv run main.py --file urls.txt

# Force re-discovery
uv run main.py --url https://example.com --force

# Show summary of all saved selectors
uv run main.py --summary

# Enable debug mode (saves extracted HTML)
uv run main.py --url https://example.com --debug
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
├── main.py                   # CLI entry point & orchestrator
├── selector_discovery.py     # AI-powered selector discovery
├── selector_validator.py     # Selector validation & testing
├── selector_storage.py       # JSON storage operations
├── services.py              # Shared services (Logfire config)
├── models.py                # Pydantic models
├── pyproject.toml           # Project config & dependencies
├── .env                     # API keys (create this)
├── CHEAT_SHEET.md          # Dev tools quick reference
└── selectors/              # Output directory
    └── selectors_*.json     # Discovered selectors per domain
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
Returns 3 selectors per field:
  - Primary (most specific)
  - Fallback (reliable backup)
  - Tertiary (generic)
  ↓
Smart fallback if AI fails
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

Selectors are saved as JSON files in the `selectors/` directory:

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
from selector_storage import SelectorStorage
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
from main import SelectorDiscoveryPipeline
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
- **Model**: `gemini-2.0-flash-exp`
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

## Development Tools

Yosoi includes a complete development toolchain:

### Setup Dev Environment

```bash
# Install with dev dependencies
uv sync --group dev

# Install pre-commit hooks
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg

# Run all checks
uv run pre-commit run --all-files
```

### Available Tools

| Tool | Purpose | Command |
|------|---------|---------|
| **Ruff** | Linting & Formatting | `uv run ruff check .` |
| **Mypy** | Type Checking | `uv run mypy .` |
| **Pre-commit** | Git Hooks | `uv run pre-commit run --all-files` |
| **Commitizen** | Conventional Commits | `uv run cz commit` |

See [CHEAT_SHEET.md](CHEAT_SHEET.md) for detailed commands.

### Commit Guidelines

Use conventional commits:

```bash
# Interactive commit
uv run cz commit

# Manual commit (must follow format)
git commit -m "feat: add new selector discovery feature"
git commit -m "fix: handle missing author tags"
git commit -m "docs: update README with examples"
```

**Commit Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance

## Features

**AI-Powered** - Uses Groq/Gemini to read HTML and find selectors
**Cheap** - $0.001 per domain
**Validated** - Tests each selector before saving
**Organized** - Clean JSON output per domain
**Fallback System** - Uses heuristics when AI fails
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
- Consider using Selenium for JavaScript-heavy sites
- Fallback heuristics will be used automatically

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

## Acknowledgments

Built with:
- [Pydantic AI](https://ai.pydantic.dev/) - AI framework
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) - HTML parsing
- [Logfire](https://logfire.pydantic.dev/) - Observability
- [Rich](https://rich.readthedocs.io/) - Terminal UI
- [Ruff](https://github.com/astral-sh/ruff) - Linting & formatting

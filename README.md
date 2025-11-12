# Web Scraper Evolution: Scraper 1-5

Five progressively advanced web scrapers, evolving from basic content extraction to an agentic queue-based system.

## Quick Start

```bash
# Install dependencies
uv sync

# Run any scraper
uv run python scraper5.py  # Most advanced
```

## Feature Comparison

| Feature | Scraper 1 | Scraper 2 | Scraper 3 | Scraper 4 | Scraper 5 |
|---------|-----------|-----------|-----------|-----------|-----------|
| **Core** |
| Content Extraction | ✅ | ❌ | ❌ | ❌ | ❌ |
| Selector Extraction | ❌ | ✅ | ✅ | ✅ | ✅ |
| Multi-URL | ❌ | ❌ | ✅ | ✅ | ✅ |
| **Retry & Errors** |
| Retry Logic | ❌ | ✅ (10x) | ✅ (3x) | ✅ (3x) | ✅ (3x) |
| Missing Field Detection | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Data Management** |
| JSON Output | ❌ | ✅ | ✅ | ✅ | ✅ |
| Aggregated Storage | ❌ | ❌ | ✅ | ✅ | ✅ |
| Source-Specific Storage | ❌ | ❌ | ❌ | ❌ | ✅ |
| Queue Persistence | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Filtering** |
| Domain Extraction | ❌ | ❌ | ✅ | ✅ | ✅ |
| Site Filtering | ❌ | ❌ | ✅ | ✅ | ✅ |
| Duplicate Detection | ❌ | ❌ | ✅ | ✅ | ✅ |
| **AI & Optimization** |
| DSPy Integration | ❌ | ❌ | ❌ | ✅ | ✅ |
| TOON Format | ❌ | ❌ | ❌ | ✅ | ✅ |
| Token Tracking | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Advanced** |
| Priority Queue | ❌ | ❌ | ❌ | ❌ | ✅ |
| Priority Selectors | ❌ | ❌ | ❌ | ❌ | ✅ |
| Anti-Bot Handling | ❌ | ❌ | ❌ | ❌ | ✅ |
| Selector Learning | ❌ | ❌ | ❌ | ❌ | ✅ |
| Auto-Promotion | ❌ | ❌ | ❌ | ❌ | ✅ |
| Rate Limiting | ❌ | ❌ | ❌ | ❌ | ✅ |

## Scraper Overview

### Scraper 1 - Foundation
Basic single-URL content extraction. Good for learning SmartScraperGraph.

**Features:** Content extraction, simple prompt, console output

### Scraper 2 - Selector Extraction
Extracts CSS selectors instead of content. Adds retry logic and validation.

**Features:** Selector extraction, 10-attempt retry, missing field detection, JSON output

### Scraper 3 - Multi-URL & Aggregation
Batch processing with filtering and aggregation.

**Features:** Multi-URL, domain tracking, site filtering, duplicate detection, timing/stats

### Scraper 4 - AI Optimization
Adds DSPy for prompt optimization and TOON for token efficiency.

**Features:** DSPy integration, TOON format (30-60% token savings), token tracking, all Scraper 3 features

### Scraper 5 - Agentic Queue System
Production-ready with priority selectors, anti-bot handling, and learning.

**Features:** Priority queue, source-specific storage, primary/fallback/tertiary selectors, anti-bot (user agents, delays, headers), selector learning with auto-promotion, queue persistence, all Scraper 4 features

## Usage Recommendations

- **Scraper 1:** Quick one-off extraction, learning
- **Scraper 2:** Single URL selector extraction
- **Scraper 3:** Batch processing, production use
- **Scraper 4:** Optimized prompts, token savings
- **Scraper 5:** Enterprise production, anti-bot, learning

## Dependencies

**All scrapers:**
- `scrapegraphai>=1.64.0`
- `langchain-google-genai>=2.0.0`
- `python-dotenv>=1.2.1`

**Scraper 4 & 5:**
- `dspy>=3.0.4`
- `toonify`

## File Structure

```
selectors.json                    # Scraper 2 output
selectors_aggregated.json        # Scraper 3 output
selectors_aggregated_4.json      # Scraper 4 output
selectors_aggregated_5.json      # Scraper 5 output
queue_state_5.json              # Scraper 5 queue state
selectors/                       # Scraper 5 source-specific
  ├── selectors_wsj_com.json
  └── selectors_virginiabusiness_com.json
```

## Notes

- All scrapers use Google Gemini 2.5 Flash
- Scrapers 3-5 support resuming interrupted sessions
- Selector priority: `aria-label` > `data-testid` > `id` > `class` > `element type`
- TOON format provides 30-60% token savings over JSON
- Scraper 5 is the most production-ready and feature-complete

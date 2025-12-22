import json
import os
import time
from datetime import datetime
from urllib.parse import urlparse

import dspy
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from scrapegraphai.graphs import SmartScraperGraph
from toon import decode, encode

# Load environment variables from .env file
load_dotenv()

# Retrieve the Gemini API key from environment variables
gemini_api_key = os.getenv('GEMINI_KEY')

if not gemini_api_key:
    raise ValueError(
        'GEMINI_KEY not found in environment variables. '
        'Please create a .env file with your GEMINI_KEY. '
        'See .env.example for reference.'
    )

# Create a LangChain model instance
llm_model = ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    google_api_key=gemini_api_key,
    temperature=0.1,
)

# Configure DSPy with LangChain model
# DSPy needs a language model wrapper for ChainOfThought optimization
try:
    from dspy.clients import LangChainLanguageModel

    # Wrap LangChain model for DSPy
    dspy_lm = LangChainLanguageModel(llm_model)
    dspy.configure(lm=dspy_lm)
    DSPY_AVAILABLE = True
except (ImportError, Exception) as e:
    print(f'\nWarning: DSPy LangChain integration failed ({e}). Using fallback prompt generation.')
    DSPY_AVAILABLE = False
    # DSPy will use fallback prompts if LM is not configured

# TOON configuration
TOON_CONFIG = {
    'delimiter': 'comma',  # Options: comma, tab, pipe
    'indent': 2,
    'key_folding': 'safe',  # Collapse nested keys for smaller payloads
}

# Define the configuration for the scraping pipeline
# Updated token count accounting for TOON efficiency (30-60% reduction)
base_tokens = 100000
# Assume 40% average savings with TOON, so we can use more tokens effectively
effective_tokens = int(base_tokens * 1.4)  # More headroom due to TOON efficiency

graph_config = {
    'llm': {'model_instance': llm_model, 'model_tokens': effective_tokens},
    'verbose': False,  # Disable verbose output for better performance
    'headless': True,  # Run headless for better performance
}

# Configuration for blocked/authenticated sites
BLOCKED_DOMAINS = [
    # Add domains that are known to block scraping or require authentication
    # Example: "example-blocked-site.com"
]

AUTHENTICATION_PATTERNS = [
    'login',
    'sign-in',
    'signin',
    'authentication',
    'auth',
    'paywall',
    'subscribe',
    'members-only',
]

urls = [
    'https://virginiabusiness.com/new-documents-reveal-scope-of-googles-chesterfield-data-center-campus/?utm_campaign=TickerTick&utm_medium=website&utm_source=tickertick.com',
    'https://www.wsj.com/tech/apple-2025-tim-cook-36af914a',
    'https://finance.yahoo.com/video/three-big-questions-left-musk-125600891.html',
]

# Output file for aggregated selectors
OUTPUT_FILE = 'selectors_aggregated_4.json'


# DSPy Signature for prompt generation
class PromptGenerationSignature(dspy.Signature):
    """Generate an optimized prompt for extracting CSS selectors from webpage HTML."""

    context: str = dspy.InputField(
        desc='Context about what selectors to extract: headline, author, date, body_text, related_content'
    )
    missing_fields: str = dspy.InputField(
        desc='Comma-separated list of missing fields that need special attention (optional)'
    )

    optimized_prompt: str = dspy.OutputField(
        desc='An optimized prompt that instructs the LLM to extract CSS selectors with priority: '
        '1) aria-label, 2) data-testid, 3) id, 4) class, 5) element type. '
        'The prompt should be clear, concise, and effective.'
    )


# DSPy Module for prompt generation with ChainOfThought reasoning
class PromptGenerationModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.generate = dspy.ChainOfThought(PromptGenerationSignature)

    def forward(self, missing_fields=None):
        """Generate optimized prompt for selector extraction using DSPy."""
        # If DSPy is not properly configured, use fallback
        if not DSPY_AVAILABLE:
            return self._generate_base_prompt(missing_fields)

        context = """Extract CSS selectors from the webpage HTML. Return ONLY a JSON object with these keys: headline, author, date, body_text, related_content.

Selector priority (use first available):
1. aria-label: '[aria-label="headline"]'
2. data-testid: '[data-testid="author"]'
3. id: '#article-title'
4. class: '.article-headline'
5. Element type: 'h1', 'time', 'article p'

Field requirements:
- headline: Main article title (usually h1)
- author: Author name or byline
- date: Publication date (check <time> tags, datetime attributes)
- body_text: Main article content (check <article>, content divs)
- related_content: Related articles/tags (optional)

Return valid CSS selectors only. No "NA" or null values."""

        missing_fields_str = ', '.join(missing_fields) if missing_fields else ''

        # Use DSPy to optimize the prompt
        try:
            result = self.generate(context=context, missing_fields=missing_fields_str)

            # Extract the optimized prompt from DSPy output
            if hasattr(result, 'optimized_prompt') and result.optimized_prompt:
                prompt = result.optimized_prompt
                # Ensure missing fields are included if provided
                if missing_fields:
                    prompt += f'\n\nMissing fields: {missing_fields_str}. Search more carefully for these elements.'
                return prompt
            # Fallback if DSPy doesn't return expected format
            return self._generate_base_prompt(missing_fields)
        except Exception:
            # Silently fall back to base prompt on error
            return self._generate_base_prompt(missing_fields)

    def _generate_base_prompt(self, missing_fields=None):
        """Fallback base prompt generation."""
        base_prompt = """Extract CSS selectors from the webpage HTML. Return ONLY a JSON object with these keys: headline, author, date, body_text, related_content.

Selector priority (use first available):
1. aria-label: '[aria-label="headline"]'
2. data-testid: '[data-testid="author"]'
3. id: '#article-title'
4. class: '.article-headline'
5. Element type: 'h1', 'time', 'article p'

Field requirements:
- headline: Main article title (usually h1)
- author: Author name or byline
- date: Publication date (check <time> tags, datetime attributes)
- body_text: Main article content (check <article>, content divs)
- related_content: Related articles/tags (optional)

Return valid CSS selectors only. No "NA" or null values."""

        if missing_fields:
            base_prompt += f'\n\nMissing fields: {", ".join(missing_fields)}. Search more carefully for these elements.'

        return base_prompt


# Initialize DSPy module for prompt generation
prompt_module = PromptGenerationModule()


# Legacy function for backward compatibility (now uses DSPy)
def get_prompt(missing_fields=None):
    """Generate prompt using DSPy module."""
    return prompt_module(missing_fields=missing_fields)


# Token tracking
token_stats = {'total_requests': 0, 'total_tokens_used': 0, 'toon_savings_bytes': 0, 'toon_savings_percent': 0.0}


def calculate_token_savings(data_dict):
    """Calculate token savings using TOON encoding."""
    try:
        # Encode as JSON
        json_str = json.dumps(data_dict, ensure_ascii=False)
        json_bytes = len(json_str.encode('utf-8'))

        # Encode as TOON
        try:
            toon_str = encode(data_dict)
            toon_bytes = len(toon_str.encode('utf-8'))
        except TypeError:
            # If encode doesn't accept the data directly, try with config
            toon_str = encode(data_dict, **TOON_CONFIG)
            toon_bytes = len(toon_str.encode('utf-8'))

        # Calculate savings
        savings_bytes = json_bytes - toon_bytes
        savings_percent = (savings_bytes / json_bytes * 100) if json_bytes > 0 else 0.0

        return {
            'json_bytes': json_bytes,
            'toon_bytes': toon_bytes,
            'savings_bytes': savings_bytes,
            'savings_percent': savings_percent,
        }
    except Exception as e:
        print(f'\nWarning: Could not calculate TOON savings: {e}')
        return None


# Function to parse result and extract selectors
def parse_result(result):
    """Parse the result from SmartScraperGraph and extract selectors."""
    selectors = None
    if isinstance(result, str):
        # Try to find JSON in the string
        try:
            # Check if result is in TOON format (simple heuristic: starts with key[ or key{)
            # For now, assume JSON format from SmartScraperGraph
            # Look for JSON object in the string
            start_idx = result.find('{')
            end_idx = result.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = result[start_idx:end_idx]
                selectors = json.loads(json_str)
            else:
                # If no JSON found, try parsing the whole string
                selectors = json.loads(result)
        except json.JSONDecodeError:
            # Try TOON decode as fallback
            try:
                selectors = decode(result)
            except Exception:
                print('\nWarning: Could not parse result as JSON or TOON.')
                return None
    elif isinstance(result, dict):
        selectors = result
    else:
        print(f'\nWarning: Unexpected result type: {type(result)}')
        return None

    # Track token savings if selectors are valid
    if selectors:
        savings = calculate_token_savings(selectors)
        if savings:
            token_stats['toon_savings_bytes'] += savings['savings_bytes']
            # Calculate running average of savings percentage
            if token_stats['total_requests'] > 0:
                # Simple running average: (old_avg * (n-1) + new_value) / n
                old_avg = token_stats['toon_savings_percent']
                new_value = savings['savings_percent']
                n = token_stats['total_requests']
                token_stats['toon_savings_percent'] = ((old_avg * (n - 1)) + new_value) / n
            else:
                token_stats['toon_savings_percent'] = savings['savings_percent']

    return selectors


# Function to check if selectors are valid
def validate_selectors(selectors):
    """Check if all required selectors are populated (not NA, null, or empty)."""
    if not selectors or not isinstance(selectors, dict):
        return False, []

    required_fields = ['headline', 'author', 'date', 'body_text']
    missing = []

    for field in required_fields:
        value = selectors.get(field, '').strip()
        if not value or value.upper() == 'NA' or value.lower() == 'null' or value == '':
            missing.append(field)

    return len(missing) == 0, missing


# Function to extract domain from URL
def extract_domain(url):
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        # Remove www. prefix if present
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return 'unknown'


# Function to check if site should be filtered
def should_filter_site(url):
    """Check if a site should be filtered due to blocking or authentication."""
    domain = extract_domain(url)

    # Check blocked domains
    if domain in BLOCKED_DOMAINS:
        return True, 'blocked_domain'

    # Check for authentication patterns in URL
    url_lower = url.lower()
    for pattern in AUTHENTICATION_PATTERNS:
        if pattern in url_lower:
            return True, f'authentication_pattern_{pattern}'

    return False, None


# Function to load existing aggregated selectors
def load_aggregated_selectors(filename):
    """Load existing aggregated selectors from JSON file."""
    if os.path.exists(filename):
        try:
            with open(filename, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f'Warning: Could not load existing file {filename}: {e}')
            return []
    return []


# Function to check if URL already exists in aggregated data
def url_exists_in_data(url, aggregated_data):
    """Check if URL already exists in aggregated data."""
    return any(entry.get('url') == url for entry in aggregated_data)


# Function to save aggregated selectors
def save_aggregated_selectors(filename, data, use_toon=False):
    """Save aggregated selectors to JSON file. Optionally use TOON format for efficiency."""
    if use_toon:
        try:
            # Save as TOON format for token efficiency
            try:
                toon_data = encode(data)
            except TypeError:
                # If encode doesn't accept the data directly, try with config
                toon_data = encode(data, **TOON_CONFIG)
            # Save with .toon extension
            toon_filename = filename.replace('.json', '.toon') if filename.endswith('.json') else f'{filename}.toon'
            with open(toon_filename, 'w', encoding='utf-8') as f:
                f.write(toon_data)
            print(f'\nSaved selectors in TOON format to: {toon_filename}')

            # Also save JSON for compatibility
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f'\nWarning: Could not save TOON format ({e}), saving as JSON only.')
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    else:
        # Standard JSON save
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# Function to scrape selectors for a single URL
def scrape_url_selectors(url, max_attempts=3):
    """Scrape selectors for a single URL with retry logic. Uses DSPy for prompt generation."""
    attempt = 0
    selectors = None
    start_time = time.time()

    print(f'\n{"=" * 80}')
    print(f'Extracting selectors from: {url}')
    print(f'{"=" * 80}')

    while attempt < max_attempts:
        attempt += 1
        token_stats['total_requests'] += 1
        print(f'\n--- Attempt {attempt}/{max_attempts} ---')

        # Get prompt using DSPy module, including missing fields if this is a retry
        missing_fields = []
        if selectors:
            _, missing_fields = validate_selectors(selectors)

        # Use DSPy module to generate optimized prompt
        prompt = get_prompt(missing_fields if missing_fields else None)

        try:
            # Create the SmartScraperGraph instance
            smart_scraper_graph = SmartScraperGraph(prompt=prompt, source=url, config=graph_config)

            # Run the pipeline
            result = smart_scraper_graph.run()

            # Parse and validate the JSON result
            print('\nRaw result:')
            print('=' * 80)
            print(result)

            # Parse the result (includes TOON token tracking)
            selectors = parse_result(result)

            if selectors is None:
                print('\nFailed to parse result. Retrying...')
                continue

            # Validate selectors
            is_valid, missing = validate_selectors(selectors)

            # Print current selectors
            print('\nExtracted Selectors:')
            print('=' * 80)
            print(json.dumps(selectors, indent=2, ensure_ascii=False))

            # Show TOON savings if available
            if selectors:
                savings = calculate_token_savings(selectors)
                if savings:
                    print(
                        f'\nTOON Token Savings: {savings["savings_percent"]:.1f}% ({savings["savings_bytes"]} bytes saved)'
                    )

            if is_valid:
                print('\n✓ All required selectors found!')
                break
            print(f'\n✗ Missing selectors: {", ".join(missing)}')
            if attempt < max_attempts:
                print('Retrying with improved prompt (DSPy optimization)...')
            else:
                print(f'\nWarning: Reached maximum attempts ({max_attempts}). Some selectors may still be missing.')
        except Exception as e:
            print(f'\nError during scraping attempt {attempt}: {e}')
            if attempt < max_attempts:
                print('Retrying...')
            else:
                print('Max attempts reached. Moving to next URL.')
                return None, attempt, time.time() - start_time

    elapsed_time = time.time() - start_time
    return selectors, attempt, elapsed_time


# Main execution
if __name__ == '__main__':
    # Load existing aggregated selectors
    aggregated_data = load_aggregated_selectors(OUTPUT_FILE)

    # Track overall timing
    total_start_time = time.time()

    print(f'\n{"=" * 80}')
    print(f'Starting selector extraction for {len(urls)} URLs')
    print(f'{"=" * 80}')

    # Iterate over URLs
    for idx, url in enumerate(urls, 1):
        print(f'\n\n{"#" * 80}')
        print(f'Processing URL {idx}/{len(urls)}')
        print(f'{"#" * 80}')

        # Check if URL already exists
        if url_exists_in_data(url, aggregated_data):
            print(f'\n⚠ URL already exists in aggregated data. Skipping: {url}')
            continue

        # Check if site should be filtered
        should_filter, filter_reason = should_filter_site(url)
        if should_filter:
            print(f'\n⚠ Site filtered ({filter_reason}). Skipping: {url}')
            # Add entry with filter status
            entry = {
                'url': url,
                'domain': extract_domain(url),
                'selectors': None,
                'timestamp': datetime.now().isoformat(),
                'status': 'filtered',
                'filter_reason': filter_reason,
                'attempts': 0,
                'elapsed_time_seconds': 0.0,
            }
            aggregated_data.append(entry)
            save_aggregated_selectors(OUTPUT_FILE, aggregated_data)
            continue

        # Scrape selectors for this URL
        try:
            selectors, attempts, elapsed_time = scrape_url_selectors(url)

            # Create entry for aggregated data
            entry = {
                'url': url,
                'domain': extract_domain(url),
                'selectors': selectors,
                'timestamp': datetime.now().isoformat(),
                'status': 'success' if selectors else 'failed',
                'attempts': attempts,
                'elapsed_time_seconds': round(elapsed_time, 2),
            }

            aggregated_data.append(entry)

            # Save after each URL (in case of interruption)
            save_aggregated_selectors(OUTPUT_FILE, aggregated_data)

            print(f'\n✓ Completed in {elapsed_time:.2f} seconds')

        except Exception as e:
            print(f'\n✗ Fatal error processing URL: {e}')
            # Add error entry
            entry = {
                'url': url,
                'domain': extract_domain(url),
                'selectors': None,
                'timestamp': datetime.now().isoformat(),
                'status': 'error',
                'error': str(e),
                'attempts': 0,
                'elapsed_time_seconds': 0.0,
            }
            aggregated_data.append(entry)
            save_aggregated_selectors(OUTPUT_FILE, aggregated_data)
            continue

    # Final summary
    total_elapsed = time.time() - total_start_time
    print(f'\n\n{"=" * 80}')
    print('Summary')
    print(f'{"=" * 80}')
    print(f'Total URLs processed: {len(urls)}')
    print(f'Total time elapsed: {total_elapsed:.2f} seconds ({total_elapsed / 60:.2f} minutes)')
    print(f'Results saved to: {OUTPUT_FILE}')

    # Token usage statistics
    if token_stats['total_requests'] > 0:
        print('\nToken Usage Statistics:')
        print(f'  Total requests: {token_stats["total_requests"]}')
        if token_stats['toon_savings_percent'] > 0:
            print(f'  Average TOON savings: {token_stats["toon_savings_percent"]:.1f}%')
            print(f'  Total bytes saved: {token_stats["toon_savings_bytes"]}')

    print(f'{"=" * 80}')

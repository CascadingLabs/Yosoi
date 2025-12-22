import json
import os
import queue
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlparse

import dspy
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from scrapegraphai.graphs import SmartScraperGraph
from toon import decode, encode

# Load environment variables
load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

gemini_api_key = os.getenv('GEMINI_KEY')
if not gemini_api_key:
    raise ValueError('GEMINI_KEY not found in environment variables. Please create a .env file with your GEMINI_KEY.')

# LLM Configuration
llm_model = ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    google_api_key=gemini_api_key,
    temperature=0,
)

# Configure DSPy
try:
    from dspy.clients import LangChainLanguageModel

    dspy_lm = LangChainLanguageModel(llm_model)
    dspy.configure(lm=dspy_lm)
    DSPY_AVAILABLE = True
except (ImportError, Exception) as e:
    print(f'\nWarning: DSPy LangChain integration failed ({e}). Using fallback.')
    DSPY_AVAILABLE = False

# TOON Configuration
TOON_CONFIG = {
    'delimiter': 'comma',
    'indent': 2,
    'key_folding': 'safe',
}

# Graph Configuration
base_tokens = 100000
effective_tokens = int(base_tokens * 1.4)

graph_config = {
    'llm': {'model_instance': llm_model, 'model_tokens': effective_tokens},
    'verbose': False,
    'headless': True,
}

# Directory for source-specific selectors
SELECTORS_DIR = 'selectors'
os.makedirs(SELECTORS_DIR, exist_ok=True)

# Output file
OUTPUT_FILE = 'selectors_aggregated_5.json'
QUEUE_STATE_FILE = 'queue_state_5.json'

# ============================================================================
# Data Models
# ============================================================================


@dataclass
class ScrapingTask:
    """Represents a scraping task in the queue."""

    url: str
    domain: str
    priority: int = 5  # 1-10, higher is more important
    status: str = 'pending'  # pending, in_progress, completed, failed
    attempts: int = 0
    source_group: str = ''  # domain for grouping
    timestamp: str = ''

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if not self.source_group:
            self.source_group = self.domain


@dataclass
class PrioritySelectors:
    """Priority-based selectors for a single field."""

    primary: str | None = None
    fallback: str | None = None
    tertiary: str | None = None
    primary_success_rate: float = 0.0
    fallback_success_rate: float = 0.0
    tertiary_success_rate: float = 0.0
    last_updated: str = ''

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()

    def to_dict(self):
        return {
            'primary': self.primary,
            'fallback': self.fallback,
            'tertiary': self.tertiary,
            'primary_success_rate': self.primary_success_rate,
            'fallback_success_rate': self.fallback_success_rate,
            'tertiary_success_rate': self.tertiary_success_rate,
            'last_updated': self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            primary=data.get('primary'),
            fallback=data.get('fallback'),
            tertiary=data.get('tertiary'),
            primary_success_rate=data.get('primary_success_rate', 0.0),
            fallback_success_rate=data.get('fallback_success_rate', 0.0),
            tertiary_success_rate=data.get('tertiary_success_rate', 0.0),
            last_updated=data.get('last_updated', datetime.now().isoformat()),
        )


# ============================================================================
# Task Queue System
# ============================================================================


class TaskQueue:
    """Priority queue for managing scraping tasks with source grouping."""

    def __init__(self):
        self.queue = queue.PriorityQueue()
        self.tasks_by_domain = defaultdict(list)
        self.all_tasks = {}  # url -> task
        self.completed_tasks = []
        self.failed_tasks = []

    def add_task(self, task: ScrapingTask):
        """Add a task to the queue. Lower priority number = higher priority."""
        # Use negative priority for max-heap behavior (lower number = higher priority)
        priority_key = (-task.priority, task.timestamp)
        self.queue.put((priority_key, task))
        self.tasks_by_domain[task.domain].append(task)
        self.all_tasks[task.url] = task

    def get_next_task(self) -> ScrapingTask | None:
        """Get next task from queue, prioritizing by source grouping."""
        if self.queue.empty():
            return None

        try:
            priority_key, task = self.queue.get_nowait()
            if task.status == 'pending':
                task.status = 'in_progress'
                return task
            # Skip if already processed, try next
            return self.get_next_task()
        except queue.Empty:
            return None

    def get_tasks_by_domain(self, domain: str) -> list[ScrapingTask]:
        """Get all tasks for a specific domain."""
        return [t for t in self.tasks_by_domain[domain] if t.status == 'pending']

    def mark_completed(self, task: ScrapingTask):
        """Mark a task as completed."""
        task.status = 'completed'
        self.completed_tasks.append(task)

    def mark_failed(self, task: ScrapingTask, error: str = ''):
        """Mark a task as failed."""
        task.status = 'failed'
        if error:
            task.error = error
        self.failed_tasks.append(task)

    def save_state(self, filename: str):
        """Save queue state to file."""
        state = {
            'pending_tasks': [
                asdict(task) for task in self.all_tasks.values() if task.status in ['pending', 'in_progress']
            ],
            'completed_tasks': [asdict(task) for task in self.completed_tasks],
            'failed_tasks': [asdict(task) for task in self.failed_tasks],
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def load_state(self, filename: str):
        """Load queue state from file."""
        if not os.path.exists(filename):
            return

        try:
            with open(filename, encoding='utf-8') as f:
                state = json.load(f)

            for task_data in state.get('pending_tasks', []):
                task = ScrapingTask(**task_data)
                task.status = 'pending'  # Reset in_progress to pending
                self.add_task(task)

            self.completed_tasks = [ScrapingTask(**task_data) for task_data in state.get('completed_tasks', [])]
            self.failed_tasks = [ScrapingTask(**task_data) for task_data in state.get('failed_tasks', [])]
        except Exception as e:
            print(f'Warning: Could not load queue state: {e}')


# ============================================================================
# Source Manager
# ============================================================================


class SourceManager:
    """Manages source-specific selector storage and retrieval."""

    def __init__(self, selectors_dir: str = SELECTORS_DIR):
        self.selectors_dir = selectors_dir
        os.makedirs(selectors_dir, exist_ok=True)

    def get_selector_file(self, domain: str) -> str:
        """Get the file path for a domain's selectors."""
        # Sanitize domain for filename
        safe_domain = domain.replace('.', '_').replace('/', '_')
        return os.path.join(self.selectors_dir, f'selectors_{safe_domain}.json')

    def load_selectors(self, domain: str) -> dict | None:
        """Load selectors for a domain."""
        filepath = self.get_selector_file(domain)
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f'Warning: Could not load selectors for {domain}: {e}')
            return None

    def save_selectors(self, domain: str, selectors: dict):
        """Save selectors for a domain."""
        filepath = self.get_selector_file(domain)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(selectors, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f'Warning: Could not save selectors for {domain}: {e}')

    def has_selectors(self, domain: str) -> bool:
        """Check if selectors exist for a domain."""
        filepath = self.get_selector_file(domain)
        return os.path.exists(filepath)


# ============================================================================
# Priority Selector Manager
# ============================================================================


class SelectorManager:
    """Manages priority-based selectors (primary/fallback/tertiary) per field."""

    def __init__(self, source_manager: SourceManager):
        self.source_manager = source_manager
        self.field_names = ['headline', 'author', 'date', 'body_text', 'related_content']

    def load_priority_selectors(self, domain: str) -> dict[str, PrioritySelectors]:
        """Load priority selectors for a domain."""
        data = self.source_manager.load_selectors(domain)
        if not data:
            return {}

        selectors = {}
        for field in self.field_names:
            if field in data:
                selectors[field] = PrioritySelectors.from_dict(data[field])
            else:
                selectors[field] = PrioritySelectors()

        return selectors

    def save_priority_selectors(self, domain: str, selectors: dict[str, PrioritySelectors]):
        """Save priority selectors for a domain."""
        # Check if we have any actual selector values
        has_any_selectors = any(ps.primary or ps.fallback or ps.tertiary for ps in selectors.values())

        if not has_any_selectors:
            print(f'  ⚠ Skipping save for {domain}: No valid selectors to save')
            return

        data = {'domain': domain, 'last_updated': datetime.now().isoformat(), 'version': '1.0'}

        for field, priority_selector in selectors.items():
            data[field] = priority_selector.to_dict()

        self.source_manager.save_selectors(domain, data)
        print(f'  ✓ Saved selectors for {domain}')

    def convert_flat_to_priority(self, flat_selectors: dict[str, str]) -> dict[str, PrioritySelectors]:
        """Convert flat selector dict to priority-based structure."""
        priority_selectors = {}

        for field in self.field_names:
            selector_value = flat_selectors.get(field)
            if selector_value:
                # Determine priority based on selector type
                priority = self._determine_selector_priority(selector_value)

                ps = PrioritySelectors()
                if priority == 'primary':
                    ps.primary = selector_value
                elif priority == 'fallback':
                    ps.fallback = selector_value
                else:
                    ps.tertiary = selector_value

                priority_selectors[field] = ps
            else:
                priority_selectors[field] = PrioritySelectors()

        return priority_selectors

    def _determine_selector_priority(self, selector: str) -> str:
        """Determine selector priority based on its type."""
        selector_lower = selector.lower()

        # Primary: aria-label, data-testid
        if '[aria-label' in selector_lower or '[data-testid' in selector_lower:
            return 'primary'

        # Fallback: id, specific classes
        if selector.startswith('#') or (selector.startswith('.') and len(selector.split()) == 1):
            return 'fallback'

        # Tertiary: element types, complex selectors
        return 'tertiary'

    def get_best_selector(self, field: str, priority_selectors: dict[str, PrioritySelectors]) -> str | None:
        """Get the best available selector for a field."""
        if field not in priority_selectors:
            return None

        ps = priority_selectors[field]

        # Return first available in priority order
        if ps.primary:
            return ps.primary
        if ps.fallback:
            return ps.fallback
        if ps.tertiary:
            return ps.tertiary

        return None

    def update_success_rate(
        self, field: str, selector_type: str, success: bool, priority_selectors: dict[str, PrioritySelectors]
    ):
        """Update success rate for a selector."""
        if field not in priority_selectors:
            return

        ps = priority_selectors[field]
        rate_attr = f'{selector_type}_success_rate'

        current_rate = getattr(ps, rate_attr, 0.0)
        # Simple moving average
        new_rate = (current_rate * 0.9) + (1.0 if success else 0.0) * 0.1
        setattr(ps, rate_attr, new_rate)
        ps.last_updated = datetime.now().isoformat()


# ============================================================================
# Anti-Bot Handler
# ============================================================================


class AntiBotHandler:
    """Handles anti-bot evasion techniques."""

    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
        self.domain_delays = defaultdict(float)  # Track last request time per domain
        self.domain_request_counts = defaultdict(int)  # Track request count per domain
        self.min_delay = 2.0  # Minimum delay between requests (seconds)
        self.max_delay = 5.0  # Maximum delay
        self.rate_limit_per_domain = 10  # Max requests per minute per domain

    def get_random_user_agent(self) -> str:
        """Get a random user agent."""
        return random.choice(self.user_agents)

    def get_headers(self) -> dict[str, str]:
        """Get randomized HTTP headers."""
        user_agent = self.get_random_user_agent()

        return {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': random.choice(
                [
                    'en-US,en;q=0.9',
                    'en-GB,en;q=0.9',
                    'en-CA,en;q=0.9',
                ]
            ),
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

    def should_delay(self, domain: str) -> bool:  # No existing primary, use new one
        """Check if we should delay before next request to this domain."""
        last_request = self.domain_delays[domain]
        if last_request == 0:
            return True

        time_since_last = time.time() - last_request
        return time_since_last < self.min_delay

    def get_delay(self, domain: str) -> float:
        """Get delay time for a domain (exponential backoff on failures)."""
        request_count = self.domain_request_counts[domain]

        # Exponential backoff if many requests
        if request_count > self.rate_limit_per_domain:
            base_delay = self.min_delay * (2 ** min(request_count // self.rate_limit_per_domain, 3))
        else:
            base_delay = self.min_delay

        # Add random jitter
        delay = base_delay + random.uniform(0, self.max_delay - base_delay)
        return min(delay, self.max_delay)

    def wait_if_needed(self, domain: str):
        """Wait if needed before making a request."""
        if self.should_delay(domain):
            delay = self.get_delay(domain)
            time.sleep(delay)

        self.domain_delays[domain] = time.time()
        self.domain_request_counts[domain] += 1

    def reset_domain_counters(self, domain: str):
        """Reset counters for a domain (call periodically)."""
        # Reset every minute
        if self.domain_request_counts[domain] > 0:
            self.domain_request_counts[domain] = max(0, self.domain_request_counts[domain] - 1)


# ============================================================================
# Enhanced Selector Extractor with DSPy
# ============================================================================


class PrioritySelectorExtractionSignature(dspy.Signature):
    """DSPy signature for extracting priority-based selectors."""

    html_content: str = dspy.InputField(desc='HTML content of the webpage')
    missing_fields: str = dspy.InputField(desc='Comma-separated missing fields (optional)')

    selectors_json: str = dspy.OutputField(
        desc="CRITICAL: Return CSS SELECTOR STRINGS (like 'h1.title', '.author', '#date'), NOT the actual content text. "
        'Analyze the HTML structure and identify CSS selectors that target each field. '
        'Return JSON with selectors for headline, author, date, body_text, related_content. '
        'For each field, provide primary (best), fallback, and tertiary CSS selectors. '
        'Priority: 1) aria-label, 2) data-testid, 3) id, 4) class, 5) element type. '
        'Return format: {"headline": {"primary": "h1.article-title", "fallback": "[data-testid=\'headline\']", "tertiary": "h1"}, ...}'
    )


class PrioritySelectorExtractionModule(dspy.Module):
    """DSPy module for extracting priority-based selectors."""

    def __init__(self):
        super().__init__()
        self.generate = dspy.ChainOfThought(PrioritySelectorExtractionSignature)

    def __call__(self, missing_fields=None):
        """Generate prompt for priority selector extraction."""
        if not DSPY_AVAILABLE:
            return self._generate_base_prompt(missing_fields)

        missing_fields_str = ', '.join(missing_fields) if missing_fields else ''

        try:
            result = self.generate(
                html_content='[HTML content will be provided by SmartScraperGraph]', missing_fields=missing_fields_str
            )

            if hasattr(result, 'selectors_json') and result.selectors_json:
                prompt = result.selectors_json
                if missing_fields:
                    prompt += f'\n\nMissing fields: {missing_fields_str}. Focus on finding these.'
                return prompt
            return self._generate_base_prompt(missing_fields)
        except Exception:
            return self._generate_base_prompt(missing_fields)

    def _generate_base_prompt(self, missing_fields=None):
        """Fallback base prompt."""
        base = """CRITICAL: Analyze the ACTUAL HTML structure of this webpage to find CSS selectors.

Your task:
1. Look at the HTML elements on this specific page
2. Find the ACTUAL class names, IDs, and attributes that exist
3. Return CSS selectors that will match those real elements

For each field (headline, author, date, body_text, related_content):
- Primary: Most specific selector (use actual data-testid, aria-label, or unique classes you see in HTML)
- Fallback: Moderately specific (use actual class names or IDs you see)
- Tertiary: Generic fallback (element types like h1, time, article p)

Return JSON format:
{
  "headline": {"primary": "...", "fallback": "...", "tertiary": "..."},
  "author": {"primary": "...", "fallback": "...", "tertiary": "..."},
  "date": {"primary": "...", "fallback": "...", "tertiary": "..."},
  "body_text": {"primary": "...", "fallback": "...", "tertiary": "..."},
  "related_content": {"primary": "...", "fallback": "...", "tertiary": "..."}
}

IMPORTANT:
- Use ACTUAL selectors from THIS page's HTML
- DO NOT use generic guesses or made-up class names
- If you cannot find a good selector, use "NA"
- Return CSS selectors, NOT content text"""

        if missing_fields:
            base += f'\n\nMissing fields: {", ".join(missing_fields)}. Search carefully for CSS selectors targeting these fields.'

        return base


# Initialize DSPy module
priority_selector_module = PrioritySelectorExtractionModule()

# ============================================================================
# Main Scraping Agent
# ============================================================================


class ScrapingAgent:
    """Main agent that orchestrates queue, selectors, and anti-bot handling."""

    def __init__(self):
        self.task_queue = TaskQueue()
        self.source_manager = SourceManager()
        self.selector_manager = SelectorManager(self.source_manager)
        self.antibot = AntiBotHandler()
        self.token_stats = {'total_requests': 0, 'toon_savings_bytes': 0, 'toon_savings_percent': 0.0}

    def add_urls(self, urls: list[str], priorities: list[int] | None = None):
        """Add URLs to the queue."""
        if priorities is None:
            priorities = [5] * len(urls)

        for url, priority in zip(urls, priorities, strict=False):
            domain = self._extract_domain(url)
            task = ScrapingTask(url=url, domain=domain, priority=priority, source_group=domain)
            self.task_queue.add_task(task)

    def process_queue(self, max_tasks: int | None = None):
        """Process tasks from the queue."""
        processed = 0

        while True:
            if max_tasks and processed >= max_tasks:
                break

            task = self.task_queue.get_next_task()
            if not task:
                break

            print(f'\n{"=" * 80}')
            print(f'Processing: {task.url}')
            print(f'Domain: {task.domain} | Priority: {task.priority}')
            print(f'{"=" * 80}')

            # Anti-bot delay
            self.antibot.wait_if_needed(task.domain)

            # Process task
            success = self._process_task(task)

            if success:
                self.task_queue.mark_completed(task)
            else:
                task.attempts += 1
                if task.attempts < 3:
                    # Retry
                    task.status = 'pending'
                    self.task_queue.add_task(task)
                else:
                    self.task_queue.mark_failed(task, 'Max attempts reached')

            processed += 1

            # Save state periodically
            if processed % 5 == 0:
                self.task_queue.save_state(QUEUE_STATE_FILE)

        # Final save
        self.task_queue.save_state(QUEUE_STATE_FILE)

    def _process_task(self, task: ScrapingTask) -> bool:
        """Process a single task with selector learning."""
        # Check if we have existing selectors for this domain
        existing_selectors = self.selector_manager.load_priority_selectors(task.domain)

        # Extract selectors using DSPy
        selectors = self._extract_selectors(task.url, existing_selectors)

        if not selectors:
            print(f'  ✗ Failed to extract selectors from {task.url}')
            # Only update failure rates if we have existing selectors with actual values
            if existing_selectors:
                has_any_selectors = any(ps.primary or ps.fallback or ps.tertiary for ps in existing_selectors.values())
                if has_any_selectors:
                    # Only update failure rates if we have real selectors to test
                    for field in ['headline', 'author', 'date', 'body_text']:
                        if field in existing_selectors:
                            ps = existing_selectors[field]
                            # Mark all as failed
                            if ps.primary:
                                self.selector_manager.update_success_rate(field, 'primary', False, existing_selectors)
                            if ps.fallback:
                                self.selector_manager.update_success_rate(field, 'fallback', False, existing_selectors)
                            if ps.tertiary:
                                self.selector_manager.update_success_rate(field, 'tertiary', False, existing_selectors)
                    self.selector_manager.save_priority_selectors(task.domain, existing_selectors)
            return False

        # Debug: Print extracted selectors
        print(f'  📋 Extracted selectors: {json.dumps(selectors, indent=2, ensure_ascii=False)[:500]}')

        # Validate selectors - actually test them on the page
        is_valid, missing = self._validate_selectors(task.url, selectors)

        # Convert to priority format
        if selectors and isinstance(next(iter(selectors.values()), None), dict):
            # Already in priority dict format - convert to PrioritySelectors objects
            priority_selectors = {}
            for field in self.selector_manager.field_names:
                if field in selectors:
                    priority_selectors[field] = PrioritySelectors.from_dict(selectors[field])
                else:
                    priority_selectors[field] = PrioritySelectors()
        else:
            priority_selectors = self.selector_manager.convert_flat_to_priority(selectors)

        # Debug: Check if we got any actual selector values
        has_selectors = any(ps.primary or ps.fallback or ps.tertiary for ps in priority_selectors.values())
        if not has_selectors:
            print('  ⚠ Warning: No valid selectors found after conversion')
            return False

        # Merge with existing and update success rates
        if existing_selectors:
            for field in priority_selectors:
                if field in existing_selectors:
                    existing_ps = existing_selectors[field]
                    new_ps = priority_selectors[field]

                    # Determine which selector type was used
                    # Primary
                    if new_ps.primary and new_ps.primary != 'NA':
                        if not existing_ps.primary or existing_ps.primary == 'NA':
                            # No existing primary, use new one
                            existing_ps.primary = new_ps.primary
                            print(f'  ➕ Added primary selector for {field}: {new_ps.primary}')
                        elif existing_ps.primary != new_ps.primary:
                            # Different primary found - keep existing for now
                            print(
                                f'  ℹ Found different primary for {field}: {new_ps.primary} (keeping {existing_ps.primary})'
                            )

                    # Fallback
                    if new_ps.fallback and new_ps.fallback != 'NA':
                        if not existing_ps.fallback or existing_ps.fallback == 'NA':
                            existing_ps.fallback = new_ps.fallback
                            print(f'  ➕ Added fallback selector for {field}: {new_ps.fallback}')

                    # Tertiary
                    if new_ps.tertiary and new_ps.tertiary != 'NA':
                        if not existing_ps.tertiary or existing_ps.tertiary == 'NA':
                            existing_ps.tertiary = new_ps.tertiary
                            print(f'  ➕ Added tertiary selector for {field}: {new_ps.tertiary}')

                    priority_selectors[field] = existing_ps
                else:
                    # New field - priority_selectors already has the correct value
                    print(f'  ➕ Added new field {field} with selectors')

        # Save selectors with updated success rates
        self.selector_manager.save_priority_selectors(task.domain, priority_selectors)

        if is_valid:
            print(f'✓ Successfully extracted all selectors for {task.domain}')
        else:
            print(f'⚠ Extracted selectors with missing fields: {", ".join(missing)}')

        return True

    def _extract_selectors(self, url: str, existing_selectors: dict) -> dict[str, str] | None:
        """Extract selectors from a URL using SmartScraperGraph."""
        # Determine missing fields from existing selectors
        missing_fields = []
        if existing_selectors:
            for field in ['headline', 'author', 'date', 'body_text']:
                if not self.selector_manager.get_best_selector(field, existing_selectors):
                    missing_fields.append(field)

        if not missing_fields and existing_selectors:
            print('  ℹ All selectors exist for this domain, validating...')

        # Generate prompt using DSPy
        prompt = priority_selector_module(missing_fields if missing_fields else None)

        try:
            smart_scraper = SmartScraperGraph(prompt=prompt, source=url, config=graph_config)

            result = smart_scraper.run()
            self.token_stats['total_requests'] += 1

            # Debug: Print raw result
            print(f'  🔍 Raw result type: {type(result)}')
            if isinstance(result, str):
                print(f'  🔍 Raw result (first 500 chars): {result[:500]}')
            elif isinstance(result, dict):
                print(f'  🔍 Raw result keys: {list(result.keys())}')

            # Track TOON savings
            if isinstance(result, (str, dict)):
                try:
                    data_to_encode = result if isinstance(result, dict) else json.loads(result)
                    json_str = json.dumps(data_to_encode, ensure_ascii=False)
                    json_bytes = len(json_str.encode('utf-8'))

                    try:
                        toon_str = encode(data_to_encode)
                        toon_bytes = len(toon_str.encode('utf-8'))
                        savings = json_bytes - toon_bytes
                        savings_percent = (savings / json_bytes * 100) if json_bytes > 0 else 0.0

                        self.token_stats['toon_savings_bytes'] += savings
                        if self.token_stats['total_requests'] > 0:
                            old_avg = self.token_stats['toon_savings_percent']
                            new_value = savings_percent
                            n = self.token_stats['total_requests']
                            self.token_stats['toon_savings_percent'] = ((old_avg * (n - 1)) + new_value) / n
                        else:
                            self.token_stats['toon_savings_percent'] = savings_percent
                    except Exception:
                        pass
                except Exception:
                    pass

            # Parse result
            selectors = self._parse_result(result)

            # Debug: Print parsed selectors
            if selectors:
                print(f'  ✓ Parsed selectors: {list(selectors.keys())}')
            else:
                print('  ✗ Failed to parse selectors from result')

            if selectors:
                # If we got priority format, extract primary selectors
                if isinstance(selectors.get('headline'), dict):
                    # Already in priority format
                    first_field = next(iter(selectors.values()), {})
                    if any(k in first_field for k in ['primary', 'fallback', 'tertiary']):
                        # Already in the format we want - return as-is
                        return selectors
                    # Dict but not priority format, flatten it
                    flat_selectors = {}
                    for field, priority_dict in selectors.items():
                        if isinstance(priority_dict, dict):
                            flat_selectors[field] = (
                                priority_dict.get('primary')
                                or priority_dict.get('fallback')
                                or priority_dict.get('tertiary')
                            )
                        else:
                            flat_selectors[field] = priority_dict
                    return flat_selectors
                # Flat format, return as-is
                return selectors

            return None
        except Exception as e:
            print(f'  ✗ Error extracting selectors: {e}')
            return None

    def _parse_result(self, result) -> dict | None:
        """Parse result from SmartScraperGraph."""
        if isinstance(result, str):
            try:
                # Try to find JSON in the string
                start_idx = result.find('{')
                end_idx = result.rfind('}') + 1
                if start_idx != -1 and end_idx > start_idx:
                    json_str = result[start_idx:end_idx]
                    parsed = json.loads(json_str)
                    return self._extract_selectors_from_parsed(parsed)
                return json.loads(result)
            except json.JSONDecodeError as e:
                print(f'  ⚠ JSON decode error: {e}')
                try:
                    return decode(result)
                except Exception as decode_error:
                    print(f'  ⚠ TOON decode error: {decode_error}')
                    return None
        elif isinstance(result, dict):
            return self._extract_selectors_from_parsed(result)
        return None

    def _extract_selectors_from_parsed(self, parsed: dict) -> dict | None:
        """Extract selectors from parsed result, handling 'content' wrapper."""
        if not parsed or not isinstance(parsed, dict):
            return None

        # Check if wrapped in 'content' key
        if 'content' in parsed and isinstance(parsed['content'], dict):
            parsed = parsed['content']

        # Now validate it's actual selectors
        if not parsed:
            return None

        first_value = next(iter(parsed.values()), None)

        # Check if it's in priority format (primary, fallback, tertiary)
        if isinstance(first_value, dict) and any(k in first_value for k in ['primary', 'fallback', 'tertiary']):
            # Validate these are actually CSS selectors, not content
            for field, priority_dict in parsed.items():
                if isinstance(priority_dict, dict):
                    for priority_level in ['primary', 'fallback', 'tertiary']:
                        selector = priority_dict.get(priority_level)
                        if selector and selector != 'NA':
                            # Check if it looks like a selector
                            if self._looks_like_selector(selector):
                                return parsed  # Valid selector found
            print("  ⚠ Priority format dict doesn't contain valid CSS selectors")
            return None
        # Check if it's flat format (field -> selector string)
        if isinstance(first_value, str):
            if self._looks_like_selector(first_value):
                return parsed
            print(f"  ⚠ Values don't look like CSS selectors: {first_value[:100]}")
            return None
        return None

    def _looks_like_selector(self, value: str) -> bool:
        """Check if a string looks like a CSS selector."""
        if not value or value == 'NA' or value.lower() == 'null':
            return False

        if len(value) > 200:
            return False

        selector_indicators = [
            value.startswith('.'),
            value.startswith('#'),
            value.startswith('['),
            value.startswith(
                (
                    'h1',
                    'h2',
                    'h3',
                    'h4',
                    'h5',
                    'h6',
                    'p',
                    'div',
                    'span',
                    'article',
                    'time',
                    'a',
                    'li',
                    'ul',
                    'ol',
                    'aside',
                )
            ),
            '[' in value,
            '.' in value,
            '#' in value,
        ]

        # If it looks like a sentence it's content
        if ' ' in value and value.count(' ') > 5:
            return False

        return any(selector_indicators)

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return 'unknown'

    def _validate_selectors(self, url: str, selectors: dict) -> tuple[bool, list[str]]:
        """Validate selectors by actually testing them on the page."""
        if not selectors or not isinstance(selectors, dict):
            return False, ['headline', 'author', 'date', 'body_text']

        try:
            # Fetch the page
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')

            required_fields = ['headline', 'author', 'date', 'body_text']
            missing = []

            for field in required_fields:
                if field not in selectors:
                    missing.append(field)
                    continue

                field_selectors = selectors[field]
                found = False

                # Try each priority level
                for priority in ['primary', 'fallback', 'tertiary']:
                    if isinstance(field_selectors, dict):
                        selector = field_selectors.get(priority)
                    else:
                        selector = field_selectors

                    if selector and selector != 'NA':
                        try:
                            element = soup.select_one(selector)
                            if element and element.get_text(strip=True):
                                found = True
                                print(f"  ✓ {field} ({priority}): '{selector}' found element")
                                break
                        except Exception:
                            continue

                if not found:
                    missing.append(field)
                    print(f'  ✗ {field}: no selector found elements')

            return len(missing) == 0, missing

        except Exception as e:
            print(f'  ⚠ Validation error: {e}')
            # If we can't validate, assume selectors are okay
            return True, []

    def print_summary(self):
        """Print summary statistics."""
        print(f'\n{"=" * 80}')
        print('Summary')
        print(f'{"=" * 80}')
        print(f'Completed: {len(self.task_queue.completed_tasks)}')
        print(f'Failed: {len(self.task_queue.failed_tasks)}')
        print(f'Total requests: {self.token_stats["total_requests"]}')
        if self.token_stats['toon_savings_percent'] > 0:
            print(
                f'TOON savings: {self.token_stats["toon_savings_percent"]:.1f}% ({self.token_stats["toon_savings_bytes"]} bytes)'
            )

        # Show selector files created
        selector_files = [f for f in os.listdir(self.source_manager.selectors_dir) if f.endswith('.json')]
        if selector_files:
            print(f'\nSelector files created: {len(selector_files)}')
            for f in selector_files[:5]:  # Show first 5
                print(f'  - {f}')
            if len(selector_files) > 5:
                print(f'  ... and {len(selector_files) - 5} more')

        print(f'{"=" * 80}')


# ============================================================================
# Main Execution
# ============================================================================

if __name__ == '__main__':
    urls = [
        'https://virginiabusiness.com/new-documents-reveal-scope-of-googles-chesterfield-data-center-campus/?utm_campaign=TickerTick&utm_medium=website&utm_source=tickertick.com',
        'https://www.wsj.com/tech/apple-2025-tim-cook-36af914a',
        'https://finance.yahoo.com/video/three-big-questions-left-musk-125600891.html',
    ]

    agent = ScrapingAgent()

    # Load previous queue state if exists
    agent.task_queue.load_state(QUEUE_STATE_FILE)

    # Add URLs
    agent.add_urls(urls, priorities=[5, 5, 5])

    # Process queue
    print(f'\nStarting queue processing for {len(urls)} URLs...')
    agent.process_queue()

    # Print summary
    agent.print_summary()

"""Simple tracker for LLM calls and URL counts per domain.

Stores everything in a single stats.json file.
"""

import json
import os
from typing import TypedDict
from urllib.parse import urlparse

from yosoi.utils.files import get_tracking_path


class DomainStats(TypedDict):
    """Per-domain tracking statistics."""

    llm_calls: int
    url_count: int
    level_distribution: dict[str, int]
    total_elapsed: float
    partial_rediscovery_count: int


class LLMTracker:
    """Tracks LLM calls and URL counts per domain in a separate file.

    Attributes:
        tracking_file: Path to the JSON file storing tracking data

    """

    def __init__(self, tracking_file: str | None = None):
        """Initialize the tracker.

        Args:
            tracking_file: Path to the JSON file for storing tracking data. Defaults to 'stats.json'.

        """
        if tracking_file is None:
            self.tracking_file = str(get_tracking_path())
        else:
            self.tracking_file = tracking_file
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create tracking file if it doesn't exist."""
        if not os.path.exists(self.tracking_file):
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.tracking_file), exist_ok=True)
            with open(self.tracking_file, 'w') as f:
                json.dump({}, f, indent=2)

    def _load_data(self) -> dict[str, DomainStats]:
        """Load tracking data from file.

        Returns:
            Dictionary mapping domain names to their DomainStats.
            Empty dict if file doesn't exist or is invalid.

        """
        try:
            with open(self.tracking_file) as f:
                data: dict[str, DomainStats] = json.load(f)
                return data
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_data(self, data: dict[str, DomainStats]) -> None:
        """Save tracking data to file.

        Args:
            data: Dictionary of tracking data to save

        """
        with open(self.tracking_file, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def extract_domain(self, url: str) -> str:
        """Extract domain from URL.

        Removes 'www.' prefix if present.

        Args:
            url: URL to extract domain from

        Returns:
            Domain name without 'www.' prefix, or 'unknown' if URL is invalid.

        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except ValueError:
            return 'unknown'

    def record_url(
        self,
        url: str,
        used_llm: bool = False,
        level_distribution: dict[str, int] | None = None,
        elapsed: float | None = None,
        partial_discovery: bool = False,
    ) -> DomainStats:
        """Record that a URL was processed.

        Args:
            url: The URL that was processed
            used_llm: Whether LLM was called for this URL. Defaults to False.
            level_distribution: Count of verified fields by selector strategy level. Defaults to None.
            elapsed: Time in seconds spent processing this URL. Defaults to None.
            partial_discovery: Whether partial (granular) rediscovery was used. Defaults to False.

        Returns:
            DomainStats with 'llm_calls', 'url_count', 'level_distribution', 'total_elapsed'.

        """
        domain = self.extract_domain(url)
        data = self._load_data()

        if domain not in data:
            data[domain] = {
                'llm_calls': 0,
                'url_count': 0,
                'level_distribution': {},
                'total_elapsed': 0.0,
                'partial_rediscovery_count': 0,
            }

        data[domain]['url_count'] += 1

        if used_llm:
            data[domain]['llm_calls'] += 1

        if elapsed is not None:
            data[domain].setdefault('total_elapsed', 0.0)
            data[domain]['total_elapsed'] += elapsed

        if level_distribution:
            dist: dict[str, int] = data[domain].setdefault('level_distribution', {})
            for level, count in level_distribution.items():
                dist[level] = dist.get(level, 0) + count

        if partial_discovery:
            data[domain].setdefault('partial_rediscovery_count', 0)
            data[domain]['partial_rediscovery_count'] += 1

        self._save_data(data)
        return data[domain]

    def get_llm_calls(self, url_or_domain: str) -> int:
        """Get LLM call count for a URL or domain.

        Args:
            url_or_domain: Either a full URL or domain name

        Returns:
            Number of LLM calls made for this domain.

        """
        domain = self.extract_domain(url_or_domain) if '://' in url_or_domain else url_or_domain
        stats = self._load_data().get(domain)
        return stats['llm_calls'] if stats else 0

    def get_url_count(self, url_or_domain: str) -> int:
        """Get URL count for a URL or domain.

        Args:
            url_or_domain: Either a full URL or domain name

        Returns:
            Number of URLs processed for this domain.

        """
        domain = self.extract_domain(url_or_domain) if '://' in url_or_domain else url_or_domain
        stats = self._load_data().get(domain)
        return stats['url_count'] if stats else 0

    def get_stats(self, url_or_domain: str) -> DomainStats:
        """Get all stats for a URL or domain.

        Args:
            url_or_domain: Either a full URL or domain name

        Returns:
            DomainStats for the given domain.

        """
        domain = self.extract_domain(url_or_domain) if '://' in url_or_domain else url_or_domain
        data = self._load_data()
        return data.get(
            domain,
            DomainStats(
                llm_calls=0, url_count=0, level_distribution={}, total_elapsed=0.0, partial_rediscovery_count=0
            ),
        )

    def get_all_stats(self) -> dict[str, DomainStats]:
        """Get all tracking data.

        Returns:
            Dictionary mapping domain names to their DomainStats.

        """
        return self._load_data()

    def print_stats(self) -> None:
        """Print statistics in a readable format."""
        data = self._load_data()

        if not data:
            print('\nNo tracking data yet.\n')
            return

        print('\n' + '=' * 70)
        print('LLM CALL TRACKING')
        print('=' * 70)

        # Calculate totals
        total_llm_calls = sum(stats['llm_calls'] for stats in data.values())
        total_urls = sum(stats['url_count'] for stats in data.values())

        total_elapsed = sum(stats.get('total_elapsed', 0.0) for stats in data.values())

        print(f'\nTotal LLM Calls: {total_llm_calls}')
        print(f'Total URLs Processed: {total_urls}')
        print(f'Total Elapsed: {total_elapsed:.1f}s')
        print(f'Total Domains: {len(data)}')

        print('\n' + '-' * 70)
        print('PER-DOMAIN BREAKDOWN:')
        print('-' * 70)

        # Sort by LLM calls (most calls first)
        sorted_domains = sorted(data.items(), key=lambda x: x[1]['llm_calls'], reverse=True)

        for domain, stats in sorted_domains:
            llm_calls = stats['llm_calls']
            url_count = stats['url_count']

            # Calculate efficiency
            if url_count > 0:
                efficiency = (url_count / llm_calls) if llm_calls > 0 else url_count
                print(f'\n{domain}')
                print(f'  LLM Calls: {llm_calls}')
                print(f'  URLs Processed: {url_count}')
                print(f'  URLs per LLM Call: {efficiency:.1f}')

        print('\n' + '=' * 70 + '\n')

    def reset(self, domain: str | None = None) -> None:
        """Reset tracking data.

        Args:
            domain: Specific domain to reset, or None to reset all. Defaults to None.

        """
        if domain:
            data = self._load_data()
            if domain in data:
                del data[domain]
                self._save_data(data)
                print(f'✓ Reset tracking for {domain}')
            else:
                print(f'No tracking data for {domain}')
        else:
            self._save_data({})
            print('✓ Reset all tracking data')


# Example usage
if __name__ == '__main__':
    tracker = LLMTracker()

    # Simulate scraping workflow
    print('Simulating scraping workflow...\n')

    # Article 1 from yahoo.com - need to call LLM
    print('1. First article from yahoo.com (calling LLM)')
    tracker.record_url('https://finance.yahoo.com/article-1', used_llm=True)
    print(f'   LLM calls: {tracker.get_llm_calls("finance.yahoo.com")}')
    print(f'   URL count: {tracker.get_url_count("finance.yahoo.com")}')

    # Article 2 from yahoo.com - use existing selectors
    print('\n2. Second article from yahoo.com (using cached selectors)')
    tracker.record_url('https://finance.yahoo.com/article-2', used_llm=False)
    print(f'   LLM calls: {tracker.get_llm_calls("finance.yahoo.com")}')
    print(f'   URL count: {tracker.get_url_count("finance.yahoo.com")}')

    # Article 3 from yahoo.com - selectors failed, call LLM again
    print('\n3. Third article from yahoo.com (selectors failed, re-discovery)')
    tracker.record_url('https://finance.yahoo.com/article-3', used_llm=True)
    print(f'   LLM calls: {tracker.get_llm_calls("finance.yahoo.com")}')
    print(f'   URL count: {tracker.get_url_count("finance.yahoo.com")}')

    # Article from different domain
    print('\n4. First article from cnn.com (calling LLM)')
    tracker.record_url('https://www.cnn.com/article-1', used_llm=True)
    print(f'   LLM calls: {tracker.get_llm_calls("cnn.com")}')
    print(f'   URL count: {tracker.get_url_count("cnn.com")}')

    # Print summary
    tracker.print_stats()

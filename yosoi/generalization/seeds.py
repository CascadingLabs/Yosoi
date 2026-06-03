"""Per-domain seed :class:`PageObservation` persistence for the reuse-hint MVP.

Domain-first generalization (the stable starting point): the selector cache is
keyed by domain, so when discovery succeeds on a page we stash a cheap
observation of that *seed* page under ``.yosoi/generalization/seeds/<domain>.json``.
Later, when the domain's cached recipe is about to be replayed on a *different*
page of the same domain, the recommender compares the new page against this seed
to decide whether the domain-wide reuse is safe (Yahoo ``/quote/AAPL`` →
``/quote/MSFT`` = yes; Reddit listing → ``/user/x`` = no).

One seed per domain (last writer wins) — enough for the advisory MVP. Sub-page
and cross-domain seeding is a later expansion.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from yosoi.generalization.fingerprint import PageObservation
from yosoi.utils.files import init_yosoi


def domain_key(url: str) -> str:
    """Filesystem-safe domain key for a URL (host, ``www.`` stripped).

    Mirrors the selector cache's domain-not-URL keying so a seed lines up with
    the recipe it describes.

    Args:
        url: The page URL.

    Returns:
        A safe key such as ``finance_yahoo_com`` (``unknown`` when host-less).
    """
    host = (urlsplit(url).hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    return host.replace('.', '_') or 'unknown'


def _seed_dir() -> Path:
    """Return (and create) the per-domain seed directory under the Yosoi home."""
    path = Path(init_yosoi('generalization')) / 'seeds'
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_seed(observation: PageObservation) -> Path:
    """Persist a seed observation for its domain (last writer wins).

    Args:
        observation: The discovery-time page observation to stash.

    Returns:
        The path the seed was written to.
    """
    path = _seed_dir() / f'{domain_key(observation.url)}.json'
    path.write_text(observation.model_dump_json(), encoding='utf-8')
    return path


def load_seed(url: str) -> PageObservation | None:
    """Load the stored seed observation for ``url``'s domain, if any.

    Args:
        url: A URL on the domain whose seed we want.

    Returns:
        The stored :class:`PageObservation`, or None when no seed exists yet.
    """
    path = _seed_dir() / f'{domain_key(url)}.json'
    if not path.exists():
        return None
    return PageObservation.model_validate_json(path.read_text(encoding='utf-8'))

"""Route-template canonicalization — the page-class join key.

Generalization needs a stable answer to "are these two pages the same *kind* of
page?" The cheapest honest signal is the URL **route template**: collapse the
instance-specific parts of a path (numeric ids, hashes, pagination indices) to
placeholders so that, e.g., ``/page/2/`` and ``/page/7/`` share a template while
``/author/Jane`` stays distinct from ``/tag/love/page/1/``.

Design constraints (learned from the scope-canon spike, 13-domain / 52-sample):

* **Generic, never a per-site adapter.** We collapse segments that are
  *structurally* instance-like (all-digits, long hash-ish tokens) but we do NOT
  guess that ``ted`` in ``/r/ted`` is a slug — that requires site knowledge the
  repo forbids. A human-readable word segment stays literal. This keeps the
  template a *false-split-biased* key: it may treat two genuinely-same templates
  as different (cheap: a redundant re-discovery) but it will not silently merge
  two different page classes (the CAS-83 leak).
* **Route template is a CACHE KEY, never the safety gate.** The spike showed URL
  templates fail both ways at scale (over-split on sort verbs, over-merge on
  ``/wiki/X`` vs ``/wiki/Category:X``). It is one cheap signal among several in
  :mod:`yosoi.generalization.recommend`; the deterministic content/structural
  checks are what actually guard reuse.

The output is intentionally human-readable (``/tag/{slug}/page/{num}/``) so a
maintainer can read why two pages were keyed together without running anything.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# A segment that is entirely digits -> a numeric instance id / index.
_ALL_DIGITS = re.compile(r'^\d+$')
# A long, mixed token that looks like a hash / uuid / opaque id.
_HASHISH = re.compile(r'^[A-Za-z0-9_-]{20,}$')
# A segment that contains digits AND letters (e.g. '1tmvpgl', 'abc123') — an id.
_MIXED_ID = re.compile(r'(?=.*[A-Za-z])(?=.*\d)', re.ASCII)

NUM = '{num}'
ID = '{id}'


def _classify_segment(seg: str) -> str:
    """Return the canonical placeholder for one path segment, or the segment.

    Args:
        seg: A single URL path segment (already URL-decoded by ``urlsplit``).

    Returns:
        ``{num}`` for pure-numeric segments, ``{id}`` for hash/uuid/mixed-id
        segments, otherwise the original segment lower-cased for stability.
    """
    if _ALL_DIGITS.match(seg):
        return NUM
    if _HASHISH.match(seg) or (len(seg) >= 8 and _MIXED_ID.search(seg)):
        return ID
    return seg.lower()


def route_template(url: str) -> str:
    """Reduce a URL to its route template (the page-class cache key).

    Drops scheme/host/query/fragment, then canonicalizes each path segment:
    numeric segments become ``{num}``, hash/uuid/mixed-id segments become
    ``{id}``, and ordinary word segments are kept (lower-cased). A trailing
    slash is normalized away; the root path is ``/``.

    Args:
        url: Absolute or path-only URL.

    Returns:
        A normalized template string such as ``/tag/{slug-literal}/page/{num}``.
        (Word segments stay literal — see module docstring on why we do not
        guess slugs.)

    Example:
        >>> route_template('https://qscrape.dev/tag/love/page/2/')
        '/tag/love/page/{num}'
        >>> route_template('https://qscrape.dev/author/Albert-Einstein')
        '/author/albert-einstein'
        >>> route_template('https://x.com/r/ted/comments/1tmvpgl/title/')
        '/r/ted/comments/{id}/title'
    """
    path = urlsplit(url).path
    segments = [s for s in path.split('/') if s]
    if not segments:
        return '/'
    return '/' + '/'.join(_classify_segment(s) for s in segments)


def same_route_class(seed_url: str, replay_url: str) -> bool:
    """Whether two URLs share a route template.

    Args:
        seed_url: URL the recipe was discovered on.
        replay_url: URL we are considering reusing the recipe on.

    Returns:
        True when both URLs canonicalize to the same route template.
    """
    return route_template(seed_url) == route_template(replay_url)


def same_registrable_domain(seed_url: str, replay_url: str) -> bool:
    """Whether two URLs share a host (the same-domain vs cross-domain axis).

    Uses the full host (including subdomain) deliberately: ``old.reddit.com`` and
    ``www.reddit.com`` render different DOMs, so they are treated as distinct for
    reuse purposes. Cross-subdomain generalization is a separate, opt-in concern.

    Args:
        seed_url: URL the recipe was discovered on.
        replay_url: Candidate reuse URL.

    Returns:
        True when both hosts are byte-identical (case-insensitive).
    """
    return urlsplit(seed_url).netloc.lower() == urlsplit(replay_url).netloc.lower()

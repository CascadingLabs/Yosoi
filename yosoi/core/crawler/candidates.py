"""Crawl-time contract candidate scoring for fetched pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from yosoi.generalization.fingerprint import PageFingerprint, PageObservation
from yosoi.models.contract import Contract

CandidateFit = Literal['weak', 'possible', 'likely', 'strong']

_SCHEMA_BY_CONTRACT: dict[str, frozenset[str]] = {
    'newsarticle': frozenset({'NewsArticle', 'Article', 'BlogPosting'}),
    'product': frozenset({'Product'}),
    'jobposting': frozenset({'JobPosting'}),
    'video': frozenset({'VideoObject'}),
}
_CONFLICTING_SCHEMA_BY_CONTRACT: dict[str, frozenset[str]] = {
    'newsarticle': frozenset({'CollectionPage', 'ItemList', 'Person', 'ProfilePage', 'SearchResultsPage'}),
    'product': frozenset({'CollectionPage', 'ItemList', 'SearchResultsPage'}),
    'jobposting': frozenset({'CollectionPage', 'ItemList', 'SearchResultsPage'}),
    'video': frozenset({'CollectionPage', 'ItemList', 'SearchResultsPage'}),
}
_LANDMARK_BY_CONTRACT: dict[str, frozenset[str]] = {
    'newsarticle': frozenset({'lm:article'}),
    'product': frozenset(),
    'jobposting': frozenset(),
    'video': frozenset(),
}
_PROSE_FIELD_NAMES = frozenset({'body_text', 'body', 'description', 'content', 'summary', 'article'})
_TITLE_FIELD_NAMES = frozenset({'headline', 'title', 'name'})
_AUTHOR_FIELD_NAMES = frozenset({'author', 'byline', 'channel', 'company'})
_DATE_FIELD_NAMES = frozenset({'date', 'posted_date', 'upload_date', 'published_at', 'updated_at'})
_NUMERIC_FIELD_NAMES = frozenset({'price', 'rating', 'reviews_count', 'salary', 'views'})
_METADATA_FIELD_NAMES = _AUTHOR_FIELD_NAMES | _DATE_FIELD_NAMES | _NUMERIC_FIELD_NAMES
_LISTING_LINK_DENSITY = 0.45
_DETAIL_PROSE_SHARE = 0.10
_MIN_PROSE_TAGS = 2
_MIN_VISIBLE_BODY_WORDS = 35
_TITLE_ATTR_RE = re.compile(r'(headline|title)', re.IGNORECASE)
_BODY_ATTR_RE = re.compile(r'(article|story|content|body|description|detail)', re.IGNORECASE)
_SCRIPT_PROPERTY_RE = re.compile(r'["\']?([A-Za-z_][\w-]*)["\']?\s*:')
_SCRIPT_SCHEMA_RE = re.compile(r'["\']@type["\']\s*:\s*["\'](?P<type>[A-Za-z][\w-]*)["\']')
_SCRIPT_BODY_RE = re.compile(
    r'["\']?(?:body|articleBody|description|content)["\']?\s*:\s*(?P<value>\[[^\]]+\]|["\'][^"\']+["\'])',
    re.IGNORECASE | re.DOTALL,
)
_LISTING_ATTR_RE = re.compile(
    r'(archive|card|catalog|component|grid|hero|latest|list|module|product|results|search|sidebar|ticker|tile|topstories|widget)',
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r'^\s*loading\b|\b(not found|could not be found)\b', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CrawlCandidateEntry:
    """One fetched page ranked as a scrape candidate for a contract."""

    url: str
    contract: str
    score: float
    fit: CandidateFit
    source_url: str | None
    fingerprint: PageFingerprint
    reasons: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    scrape_verified: bool = False


def contract_name(contract: str | type[Contract] | Any) -> str:
    """Return the public contract name for strings and Contract classes."""
    if isinstance(contract, str):
        return contract
    name = getattr(contract, '__name__', None)
    if isinstance(name, str) and name:
        return name
    return str(contract)


def score_contract_fit(
    contract: str | type[Contract],
    *,
    url: str,
    source_url: str | None,
    fingerprint: PageFingerprint,
    observation: PageObservation,
    html: str = '',
) -> CrawlCandidateEntry | None:
    """Return a contract candidate when fetched-page evidence supports trying scrape.

    URL and anchor text can prioritize the crawl frontier, but the candidate fit is
    based on generic fetched-page evidence: schema/structured data, landmarks,
    headings, prose/body shape, listing shape, and useful metadata. It does not
    claim extraction success; ``scrape_verified`` stays false until ``ys.scrape``
    is actually run by a caller.
    """
    name = contract_name(contract)
    key = _contract_key(name)
    evidence = extract_crawl_evidence(
        contract_name=name,
        contract_key=key,
        fingerprint=fingerprint,
        observation=observation,
        html=html,
    )
    if _has_conflicting_page_schema(key, fingerprint, evidence):
        return None
    if key == 'newsarticle' and _is_root_page(url) and not _has_direct_article_structure(evidence):
        return None
    if key == 'newsarticle' and not evidence.structure:
        return None

    reasons = evidence.raw_reasons
    if not reasons:
        return None

    fit = _candidate_fit(evidence)
    score = _candidate_score(evidence)
    return CrawlCandidateEntry(
        url=url,
        contract=name,
        score=score,
        fit=fit,
        source_url=source_url,
        fingerprint=fingerprint,
        reasons=tuple(reasons),
        evidence=tuple(evidence.labels),
        scrape_verified=False,
    )


@dataclass(frozen=True, slots=True)
class CrawlEvidence:
    """Generic fetched-page signals used to rank scrape candidates."""

    structure: bool = False
    title: bool = False
    body: bool = False
    metadata: bool = False
    listing: bool = False
    labels: tuple[str, ...] = ()
    raw_reasons: tuple[str, ...] = ()


def extract_crawl_evidence(
    *,
    contract_name: str,
    contract_key: str,
    fingerprint: PageFingerprint,
    observation: PageObservation,
    html: str = '',
) -> CrawlEvidence:
    """Extract contract-fit signals from a fetched page without site-specific rules."""
    labels: list[str] = []
    raw: list[str] = []

    schema_types = _matching_schema_types(contract_name, contract_key, fingerprint)
    embedded_schema_types = _embedded_schema_types(html, contract_name, contract_key)
    if embedded_schema_types:
        schema_types = tuple(sorted(set(schema_types) | set(embedded_schema_types)))
    schema_fields = _structured_property_names(html)
    visible_title, visible_body = _visible_detail_signals(html)
    embedded_body = _embedded_body_signal(html)
    landmarks = _matching_landmarks(contract_key, fingerprint)
    headings = sorted(feature for feature in fingerprint.semantic if feature.startswith('h1:'))

    prose_tags = _prose_tag_count(observation)
    link_count = observation.tag_hist.get('a', 0)
    prose_dominant = observation.prose_share() > observation.link_density() and prose_tags >= _MIN_PROSE_TAGS
    article_body_shape = prose_tags >= _MIN_PROSE_TAGS and observation.prose_share() >= _DETAIL_PROSE_SHARE
    detail_evidence = bool(landmarks) or visible_body or embedded_body
    high_link_listing = link_count >= 20 and not detail_evidence
    listing_shape = (observation.link_density() >= _LISTING_LINK_DENSITY or high_link_listing) and not detail_evidence

    structure = _append_structure_evidence(
        labels,
        raw,
        schema_types=schema_types,
        landmarks=landmarks,
        article_body_shape=article_body_shape,
        visible_body=visible_body,
        listing_shape=listing_shape,
    )
    title = _append_title_evidence(
        labels, raw, headings=headings, schema_fields=schema_fields, visible_title=visible_title
    )
    body = _append_body_evidence(
        labels,
        raw,
        contract_key=contract_key,
        schema_fields=schema_fields,
        prose_dominant=prose_dominant,
        visible_body=visible_body,
        embedded_body=embedded_body,
    )
    metadata = _append_metadata_evidence(labels, raw, schema_fields)

    return CrawlEvidence(
        structure=structure,
        title=title,
        body=body,
        metadata=metadata,
        listing=listing_shape,
        labels=tuple(dict.fromkeys(labels)),
        raw_reasons=tuple(dict.fromkeys(raw)),
    )


def _append_structure_evidence(
    labels: list[str],
    raw: list[str],
    *,
    schema_types: tuple[str, ...],
    landmarks: tuple[str, ...],
    article_body_shape: bool,
    visible_body: bool,
    listing_shape: bool,
) -> bool:
    structure = (
        bool(landmarks)
        or (bool(schema_types) and not listing_shape)
        or ((article_body_shape or visible_body) and not listing_shape)
    )
    if schema_types:
        labels.append('structured data')
        raw.extend(f'schema:{schema_type}' for schema_type in schema_types)
    if landmarks:
        labels.append('article landmark' if 'lm:article' in landmarks else 'landmark')
        raw.extend(landmarks)
    if article_body_shape or visible_body:
        labels.append('detail page shape')
        raw.append('shape:detail')
    if listing_shape:
        labels.append('listing shape')
        raw.append('shape:listing')
    return structure


def _append_title_evidence(
    labels: list[str],
    raw: list[str],
    *,
    headings: list[str],
    schema_fields: frozenset[str],
    visible_title: bool,
) -> bool:
    title = bool(headings) or bool(schema_fields & _TITLE_FIELD_NAMES) or visible_title
    if headings:
        labels.append('headline')
        raw.append('field:headline<-heading')
    elif visible_title:
        labels.append('headline')
        raw.append('field:headline<-visible')
    elif schema_fields & _TITLE_FIELD_NAMES:
        labels.append('headline')
        raw.append('field:title<-schema')
    return title


def _append_body_evidence(
    labels: list[str],
    raw: list[str],
    *,
    contract_key: str,
    schema_fields: frozenset[str],
    prose_dominant: bool,
    visible_body: bool,
    embedded_body: bool,
) -> bool:
    schema_body = _body_schema_field_present(contract_key, schema_fields)
    body = prose_dominant or schema_body or visible_body or embedded_body
    if prose_dominant:
        labels.append('body text')
        raw.append('field:body_text<-prose')
    elif schema_body:
        labels.append('body text')
        raw.append('field:body_text<-schema')
    elif visible_body:
        labels.append('body text')
        raw.append('field:body_text<-visible')
    elif embedded_body:
        labels.append('body text')
        raw.append('field:body_text<-structured')
    return body


def _append_metadata_evidence(labels: list[str], raw: list[str], schema_fields: frozenset[str]) -> bool:
    metadata_fields = schema_fields & _METADATA_FIELD_NAMES
    if not metadata_fields:
        return False
    labels.append('metadata')
    raw.extend(f'field:{field}<-schema' for field in sorted(metadata_fields)[:3])
    return True


def _candidate_fit(evidence: CrawlEvidence) -> CandidateFit:
    if evidence.structure and evidence.title and evidence.body and not evidence.listing:
        return 'strong'
    if evidence.structure and (evidence.title or evidence.body) and evidence.metadata and not evidence.listing:
        return 'likely'
    if evidence.structure and (evidence.title or evidence.body or evidence.metadata) and not evidence.listing:
        return 'possible'
    if evidence.title and evidence.body and not evidence.listing:
        return 'possible'
    return 'weak'


def _candidate_score(evidence: CrawlEvidence) -> float:
    score = 0.0
    if evidence.structure:
        score += 0.35
    if evidence.title:
        score += 0.25
    if evidence.body:
        score += 0.25
    if evidence.metadata:
        score += 0.15
    if evidence.listing:
        score = min(score, 0.35)
    return round(min(score, 1.0), 2)


def _contract_key(contract_name: str) -> str:
    return ''.join(part for part in contract_name.lower() if part.isalnum())


def _matching_schema_types(
    contract_name: str,
    contract_key: str,
    fingerprint: PageFingerprint,
) -> tuple[str, ...]:
    schemas = _SCHEMA_BY_CONTRACT.get(contract_key, frozenset({contract_name}))
    return tuple(sorted(schema for schema in schemas if f'schema:{schema}' in fingerprint.semantic))


def _matching_landmarks(contract_key: str, fingerprint: PageFingerprint) -> tuple[str, ...]:
    landmarks = _LANDMARK_BY_CONTRACT.get(contract_key, frozenset())
    return tuple(sorted(landmark for landmark in landmarks if landmark in fingerprint.semantic))


def _has_conflicting_page_schema(
    contract_key: str,
    fingerprint: PageFingerprint,
    evidence: CrawlEvidence,
) -> bool:
    """Reject generic profile/list/search schemas unless direct target structure exists."""
    conflicting = _CONFLICTING_SCHEMA_BY_CONTRACT.get(contract_key, frozenset())
    if not any(f'schema:{schema}' in fingerprint.semantic for schema in conflicting):
        return False
    direct_structure = any(reason.startswith('schema:') or reason == 'lm:article' for reason in evidence.raw_reasons)
    return not direct_structure


def _has_direct_article_structure(evidence: CrawlEvidence) -> bool:
    return any(reason.startswith('schema:') or reason == 'lm:article' for reason in evidence.raw_reasons)


def _is_root_page(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    return not path


def _structured_property_names(html: str) -> frozenset[str]:
    if not html:
        return frozenset()
    try:
        from parsel import Selector

        blobs = Selector(text=html).css('script[type="application/ld+json"]::text').getall()
        script_blobs = Selector(text=html).xpath('//script/text()').getall()
    except (TypeError, ValueError):
        return frozenset()

    names: set[str] = set()
    for blob in blobs:
        names.update(_json_property_names_from_blob(blob))
    for blob in script_blobs:
        names.update(name.lower() for name in _SCRIPT_PROPERTY_RE.findall(blob))
    return frozenset(names)


def _json_property_names_from_blob(blob: str) -> set[str]:
    try:
        return _json_property_names(json.loads(blob))
    except (TypeError, ValueError):
        return set()


def _embedded_schema_types(html: str, contract_name: str, contract_key: str) -> tuple[str, ...]:
    if not html:
        return ()
    schemas = _SCHEMA_BY_CONTRACT.get(contract_key, frozenset({contract_name}))
    found = {match.group('type') for match in _SCRIPT_SCHEMA_RE.finditer(html)}
    return tuple(sorted(schema for schema in schemas if schema in found))


def _embedded_body_signal(html: str) -> bool:
    if not html:
        return False
    for match in _SCRIPT_BODY_RE.finditer(html):
        value = match.group('value')
        quoted_text = ' '.join(part for _quote, part in re.findall(r"""(['"])(.*?)(?<!\\)\1""", value))
        text = quoted_text or value
        if _word_count(text) >= _MIN_VISIBLE_BODY_WORDS and _usable_visible_text(text):
            return True
    return False


def _visible_detail_signals(html: str) -> tuple[bool, bool]:
    if not html:
        return False, False
    try:
        from parsel import Selector

        sel = Selector(text=html)
    except (TypeError, ValueError):
        return False, False

    title = False
    body = False
    for node in sel.xpath('//*'):
        tag = (node.xpath('name()').get() or '').lower()
        attrs = ' '.join(
            value
            for value in (
                node.attrib.get('class', ''),
                node.attrib.get('id', ''),
                node.attrib.get('itemprop', ''),
                node.attrib.get('property', ''),
            )
            if value
        )
        text = _visible_node_text(node)
        if not _usable_visible_text(text):
            continue
        if tag in {'h1', 'h2'} or _TITLE_ATTR_RE.search(attrs):
            title = True
        words = _word_count(text)
        if (
            words >= _MIN_VISIBLE_BODY_WORDS
            and (tag == 'article' or _BODY_ATTR_RE.search(attrs))
            and not _looks_like_listing_node(node, attrs, words)
        ):
            body = True
        if title and body:
            return True, True
    return title, body


def _visible_node_text(node: Any) -> str:
    parts = node.xpath('.//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)]').getall()
    return ' '.join(' '.join(parts).split())


def _usable_visible_text(text: str) -> bool:
    return bool(text) and not _PLACEHOLDER_RE.search(text)


def _word_count(text: str) -> int:
    return len(re.findall(r'\w+', text))


def _looks_like_listing_node(node: Any, attrs: str, words: int) -> bool:
    if _LISTING_ATTR_RE.search(attrs):
        return True
    ancestor_attrs = ' '.join(
        value
        for value in node.xpath('ancestor::*[@class or @id]/@class | ancestor::*[@class or @id]/@id').getall()
        if value
    )
    if _LISTING_ATTR_RE.search(ancestor_attrs):
        return True
    link_count = len(node.xpath('.//a').getall())
    return link_count >= 5 and (words == 0 or link_count / words > 0.02)


def _json_property_names(data: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(key, str) and not key.startswith('@'):
                names.add(_normalize_schema_property(key))
            names.update(_json_property_names(value))
    elif isinstance(data, list):
        for item in data:
            names.update(_json_property_names(item))
    return names


def _normalize_schema_property(name: str) -> str:
    chars: list[str] = []
    for char in name:
        if char.isupper() and chars:
            chars.append('_')
        chars.append(char.lower() if char.isalnum() else '_')
    return ''.join(chars).strip('_')


def _prose_tag_count(observation: PageObservation) -> int:
    return sum(observation.tag_hist.get(tag, 0) for tag in ('p', 'blockquote', 'pre'))


def _body_schema_field_present(contract_key: str, schema_fields: frozenset[str]) -> bool:
    if contract_key == 'newsarticle':
        return bool(schema_fields & {'article_body', 'body', 'description'})
    return bool(schema_fields & _PROSE_FIELD_NAMES)

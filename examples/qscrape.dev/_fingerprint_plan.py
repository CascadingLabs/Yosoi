"""Example-local crawl→fingerprint planning for full_crawl_v2.

The crawler stays neutral: it fetches pages and computes page fingerprints. This
helper can either produce a cold-start neutral fingerprint-family fanout or rank
pages against explicit validated positive and contrastive exemplars.

This is advisory. Fingerprints propose scrape targets; they do not authorize
selector reuse or serving data. URL paths and contract/schema words are not used
for scoring. Verified scrape/discovery remains the extraction-success gate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from yosoi.generalization.fingerprint import PageFingerprint
from yosoi.models.contract import Contract
from yosoi.policy.core import Policy

if TYPE_CHECKING:
    from yosoi.core.crawler.coordinator import CrawlResult, CrawlRunSummary


@dataclass(frozen=True, slots=True)
class CrawlInventoryItem:
    """Small planning view of one successful crawled page."""

    url: str
    fingerprint: PageFingerprint
    depth: int = 0
    html_chars: int = 0
    outlinks: int = 0
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class CrawlInventory:
    """Small planning boundary derived from a crawl summary."""

    items: tuple[CrawlInventoryItem, ...]

    @classmethod
    def from_summary(cls, summary: CrawlRunSummary) -> CrawlInventory:
        """Build a planning inventory from the crawler's internal run summary."""
        return cls(tuple(_inventory_item(result) for result in summary.results if _scorable(result)))

    @property
    def urls(self) -> list[str]:
        """Successful inventory URLs in crawl order."""
        return [item.url for item in self.items]


@dataclass(frozen=True, slots=True)
class FingerprintTarget:
    """One fingerprint target candidate under one contract label."""

    contract_name: str
    contract: type[Contract]
    url: str
    family_url: str
    score: float
    weighted_jaccard_score: float
    family_cohesion_score: float
    same_shape: bool
    neutral_candidate: bool
    family_size: int
    depth: int
    html_chars: int
    outlinks: int
    content_type: str | None = None
    evidence_scope: str = 'neutral_fingerprint_family'
    contract_specific: bool = False
    best_exemplar_url: str | None = None
    exemplar_score: float | None = None
    exemplar_top_score: float | None = None
    exemplar_top3_mean_score: float | None = None
    exemplar_support_count: int | None = None
    exemplar_support_ratio: float | None = None
    exemplar_margin: float | None = None
    second_contract_name: str | None = None
    positive_exemplar_score: float | None = None
    contrastive_score: float | None = None
    contrastive_weight: float | None = None


@dataclass(frozen=True, slots=True)
class FingerprintTargetPlan:
    """Fingerprint candidate plan grouped by contract label."""

    targets: dict[str, list[FingerprintTarget]] = field(default_factory=dict)
    plan_kind: str = 'neutral_fingerprint_candidate_fanout'
    evidence_scope: str = 'neutral_fingerprint_family'
    contract_specific_ranking: bool = False
    limitations: tuple[str, ...] = (
        'Cold-start fingerprint families rank page structure only.',
        'Contracts are fanout labels; identical URL lists across contracts are expected.',
        'Run verified scrape/discovery before treating any row as contract-specific success.',
    )

    def neutral_candidate_targets(
        self, contract: type[Contract] | str, *, limit: int | None = None
    ) -> list[FingerprintTarget]:
        """Return neutral candidate objects for one contract label, in planner rank order."""
        name = contract if isinstance(contract, str) else contract.__name__
        targets = [target for target in self.targets.get(name, ()) if target.neutral_candidate]
        return targets if limit is None else targets[:limit]

    def neutral_candidate_urls(self, contract: type[Contract] | str, *, limit: int | None = None) -> list[str]:
        """Return neutral candidate URLs for one contract label, in planner rank order."""
        return [target.url for target in self.neutral_candidate_targets(contract, limit=limit)]

    def as_rows(self) -> list[dict[str, Any]]:
        """Return JSON/table-friendly rows for audit output."""
        rows: list[dict[str, Any]] = []
        for contract_name in sorted(self.targets):
            rows.extend(_target_row(target) for target in self.targets[contract_name])
        return rows

    def as_output(self) -> dict[str, Any]:
        """Return a self-describing JSON payload for persisted planning output."""
        return {
            'plan_kind': self.plan_kind,
            'evidence_scope': self.evidence_scope,
            'contract_specific_ranking': self.contract_specific_ranking,
            'verified': False,
            'limitations': list(self.limitations),
            'rows': self.as_rows(),
        }


@dataclass(frozen=True, slots=True)
class CrawlTargetWorkflowResult:
    """Output of the reusable crawl→neutral-candidate-plan→optional-scrape workflow."""

    summary: CrawlRunSummary
    inventory: CrawlInventory
    plan: FingerprintTargetPlan
    inventory_paths: dict[str, str] = field(default_factory=dict)
    scrape_results: dict[str, Any] = field(default_factory=dict)


def plan_contract_targets(
    inventory: CrawlInventory | CrawlRunSummary,
    contracts: Sequence[type[Contract]],
    *,
    family_fingerprint_score: float = 0.70,
    min_fingerprint_score: float = 0.70,
    max_targets_per_contract: int | None = None,
    contract_exemplars: Mapping[type[Contract] | str, Sequence[str]] | None = None,
    contrastive_exemplars: Sequence[str] | None = None,
    contrastive_weight: float = 0.0,
    min_exemplar_score: float = 0.70,
    min_exemplar_margin: float = 0.06,
    exemplar_support_score: float = 0.70,
    exclude_exemplars_from_targets: bool = True,
) -> FingerprintTargetPlan:
    """Rank crawled pages as fingerprint candidates for explicit contract fanout.

    No route hints and no lexical contract/page matching are accepted. Without
    exemplars, page families are discovered from fingerprints and contracts are
    only fanout labels. With exemplars, pages are ranked by positive exemplar
    similarity minus optional contrastive/no-contract similarity.
    """
    inv = inventory if isinstance(inventory, CrawlInventory) else CrawlInventory.from_summary(inventory)
    if contract_exemplars:
        return _plan_with_exemplars(
            inv,
            contracts,
            contract_exemplars=contract_exemplars,
            contrastive_exemplars=contrastive_exemplars,
            contrastive_weight=contrastive_weight,
            min_exemplar_score=min_exemplar_score,
            min_exemplar_margin=min_exemplar_margin,
            exemplar_support_score=exemplar_support_score,
            max_targets_per_contract=max_targets_per_contract,
            exclude_exemplars_from_targets=exclude_exemplars_from_targets,
        )

    families = _fingerprint_families(list(inv.items), family_fingerprint_score=family_fingerprint_score)
    planned: dict[str, list[FingerprintTarget]] = {}

    for contract in contracts:
        rows: list[FingerprintTarget] = []
        for family in families:
            for item in family.items:
                fp_score = family.item_scores[item.url]
                neutral_candidate = fp_score >= min_fingerprint_score
                if not neutral_candidate:
                    continue
                rows.append(
                    FingerprintTarget(
                        contract_name=contract.__name__,
                        contract=contract,
                        url=item.url,
                        family_url=family.representative.url,
                        score=_combined_score(
                            fp_score=fp_score,
                            family_cohesion=family.cohesion_score,
                            family_size=len(family.items),
                            item=item,
                        ),
                        weighted_jaccard_score=fp_score,
                        family_cohesion_score=family.cohesion_score,
                        same_shape=True,
                        neutral_candidate=neutral_candidate,
                        family_size=len(family.items),
                        depth=item.depth,
                        html_chars=item.html_chars,
                        outlinks=item.outlinks,
                        content_type=item.content_type,
                    )
                )
        rows = _diverse_family_order(rows)
        planned[contract.__name__] = rows if max_targets_per_contract is None else rows[:max_targets_per_contract]

    return FingerprintTargetPlan(planned)


async def crawl_contract_targets(
    seeds: str | Sequence[str],
    contracts: Sequence[type[Contract]],
    *,
    crawl_policy: Policy | None = None,
    scrape_policy: Policy | None = None,
    family_fingerprint_score: float = 0.70,
    min_fingerprint_score: float = 0.70,
    max_targets_per_contract: int | None = None,
    contract_exemplars: Mapping[type[Contract] | str, Sequence[str]] | None = None,
    contrastive_exemplars: Sequence[str] | None = None,
    contrastive_weight: float = 0.0,
    min_exemplar_score: float = 0.70,
    min_exemplar_margin: float = 0.06,
    exemplar_support_score: float = 0.70,
    exclude_exemplars_from_targets: bool = True,
    scrape_top_per_contract: int = 0,
    scrape_max_concurrency: int | None = None,
    output_dir: str | Path | None = None,
    include_query_strings: bool = False,
) -> CrawlTargetWorkflowResult:
    """Run the reusable frontier→neutral-candidate-plan→optional-verified-scrape workflow."""
    from yosoi.api import scrape
    from yosoi.core.crawler.run import crawl

    summary = await crawl(seeds, policy=crawl_policy)
    inventory = CrawlInventory.from_summary(summary)
    plan = plan_contract_targets(
        inventory,
        contracts,
        family_fingerprint_score=family_fingerprint_score,
        min_fingerprint_score=min_fingerprint_score,
        max_targets_per_contract=max_targets_per_contract,
        contract_exemplars=contract_exemplars,
        contrastive_exemplars=contrastive_exemplars,
        contrastive_weight=contrastive_weight,
        min_exemplar_score=min_exemplar_score,
        min_exemplar_margin=min_exemplar_margin,
        exemplar_support_score=exemplar_support_score,
        exclude_exemplars_from_targets=exclude_exemplars_from_targets,
    )
    paths = (
        write_target_inventory(inventory, plan, output_dir, include_query_strings=include_query_strings)
        if output_dir is not None
        else {}
    )
    scraped = await _scrape_with(
        scrape,
        plan,
        policy=scrape_policy,
        top_per_contract=scrape_top_per_contract,
        scrape_max_concurrency=scrape_max_concurrency,
    )
    return CrawlTargetWorkflowResult(
        summary=summary, inventory=inventory, plan=plan, inventory_paths=paths, scrape_results=scraped
    )


async def scrape_planned_targets(
    plan: FingerprintTargetPlan,
    *,
    policy: Policy | None = None,
    top_per_contract: int = 1,
    scrape_max_concurrency: int | None = None,
) -> dict[str, Any]:
    """Scrape top planner targets per contract using explicit Yosoi verification."""
    from yosoi.api import scrape

    return await _scrape_with(
        scrape, plan, policy=policy, top_per_contract=top_per_contract, scrape_max_concurrency=scrape_max_concurrency
    )


def write_target_inventory(
    inventory: CrawlInventory | CrawlRunSummary,
    plan: FingerprintTargetPlan,
    output_dir: str | Path,
    *,
    include_query_strings: bool = False,
) -> dict[str, str]:
    """Write crawl URL inventory and fingerprint target plan JSON files.

    Query strings are redacted by default because reusable crawl inventories may
    contain tokens or PII. Pass ``include_query_strings=True`` for trusted demos.
    """
    inv = inventory if isinstance(inventory, CrawlInventory) else CrawlInventory.from_summary(inventory)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    urls_path = out / 'frontier_urls.json'
    plan_path = out / 'fingerprint_target_plan.json'
    scores_path = out / 'fingerprint_scores.json'
    urls = [_safe_url(item.url, include_query_strings=include_query_strings) for item in inv.items]
    urls_path.write_text(json.dumps(urls, indent=2) + '\n', encoding='utf-8')
    plan_path.write_text(json.dumps(plan.as_output(), indent=2) + '\n', encoding='utf-8')
    scores_path.write_text(
        json.dumps(
            {
                'artifact_kind': 'neutral_fingerprint_all_pairs',
                'evidence_scope': 'page_fingerprint_similarity',
                'pairing': 'unordered_including_self',
                'contract_specific_ranking': False,
                'verified': False,
                'rows': _fingerprint_similarity_rows(inv),
            },
            indent=2,
        )
        + '\n',
        encoding='utf-8',
    )
    return {
        'frontier_urls': str(urls_path),
        'fingerprint_target_plan': str(plan_path),
        'fingerprint_scores': str(scores_path),
    }


async def _scrape_with(
    scrape: Any,
    plan: FingerprintTargetPlan,
    *,
    policy: Policy | None,
    top_per_contract: int,
    scrape_max_concurrency: int | None,
) -> dict[str, Any]:
    if top_per_contract <= 0:
        return {}
    scraped: dict[str, Any] = {}
    for contract_name, targets in plan.targets.items():
        contract = targets[0].contract if targets else None
        urls = [target.url for target in targets if target.neutral_candidate][:top_per_contract]
        if contract is None or not urls:
            scraped[contract_name] = {'skipped': 'no neutral fingerprint candidates'}
            continue
        allowed_types = _contract_allowed_download_types(contract)
        scraped[contract_name] = await scrape(
            urls,
            contract,
            policy=policy,
            allow_downloads=bool(allowed_types or contract.file_fields()),
            allowed_download_types=allowed_types,
            max_concurrency=scrape_max_concurrency,
        )
    return scraped


def _inventory_item(result: CrawlResult) -> CrawlInventoryItem:
    fingerprint = result.fingerprint
    if fingerprint is None:
        raise ValueError('cannot build inventory item without a fingerprint')
    return CrawlInventoryItem(
        url=result.job.url,
        fingerprint=fingerprint,
        depth=result.job.depth,
        html_chars=result.html_chars,
        outlinks=len(result.discovered_links),
        content_type=result.content_type,
    )


@dataclass(frozen=True, slots=True)
class _ExemplarScore:
    contract_name: str
    score: float
    top_score: float
    top3_mean_score: float
    support_count: int
    support_ratio: float
    best_exemplar_url: str
    best_same_shape: bool


def _plan_with_exemplars(
    inventory: CrawlInventory,
    contracts: Sequence[type[Contract]],
    *,
    contract_exemplars: Mapping[type[Contract] | str, Sequence[str]],
    contrastive_exemplars: Sequence[str] | None,
    contrastive_weight: float,
    min_exemplar_score: float,
    min_exemplar_margin: float,
    exemplar_support_score: float,
    max_targets_per_contract: int | None,
    exclude_exemplars_from_targets: bool,
) -> FingerprintTargetPlan:
    by_url = {item.url: item for item in inventory.items if not item.fingerprint.degenerate}
    exemplars: dict[str, list[CrawlInventoryItem]] = {}
    for contract in contracts:
        urls = contract_exemplars.get(contract) or contract_exemplars.get(contract.__name__) or ()
        found = [by_url[url] for url in urls if url in by_url]
        if found:
            exemplars[contract.__name__] = found
    if set(exemplars) != {contract.__name__ for contract in contracts}:
        missing = sorted({contract.__name__ for contract in contracts} - set(exemplars))
        raise ValueError(f'missing crawled fingerprint exemplars for contracts: {missing}')

    exemplar_urls = {item.url for items in exemplars.values() for item in items}
    contrastives = [by_url[url] for url in contrastive_exemplars or () if url in by_url]
    contrastive_urls = {item.url for item in contrastives}
    planned: dict[str, list[FingerprintTarget]] = {contract.__name__: [] for contract in contracts}
    for item in inventory.items:
        if item.fingerprint.degenerate:
            continue
        if exclude_exemplars_from_targets and item.url in exemplar_urls | contrastive_urls:
            continue
        contrastive_score = (
            _score_against_exemplars(
                item,
                contract_name='NoContract',
                exemplars=contrastives,
                support_score=exemplar_support_score,
            ).score
            if contrastives and contrastive_weight > 0
            else 0.0
        )
        scored = sorted(
            (
                (
                    positive.score - (contrastive_weight * contrastive_score),
                    positive,
                )
                for positive in (
                    _score_against_exemplars(
                        item,
                        contract_name=contract.__name__,
                        exemplars=exemplars[contract.__name__],
                        support_score=exemplar_support_score,
                    )
                    for contract in contracts
                )
            ),
            key=lambda score: score[0],
            reverse=True,
        )
        winner_score, winner = scored[0]
        runner_up_score, runner_up = scored[1] if len(scored) > 1 else (0.0, None)
        margin = winner_score - runner_up_score
        if winner_score < min_exemplar_score or margin < min_exemplar_margin:
            continue
        contract = next(contract for contract in contracts if contract.__name__ == winner.contract_name)
        planned[winner.contract_name].append(
            FingerprintTarget(
                contract_name=winner.contract_name,
                contract=contract,
                url=item.url,
                family_url=winner.best_exemplar_url,
                score=winner_score,
                weighted_jaccard_score=winner.top3_mean_score,
                family_cohesion_score=winner.support_ratio,
                same_shape=winner.best_same_shape,
                neutral_candidate=True,
                family_size=len(exemplars[winner.contract_name]),
                depth=item.depth,
                html_chars=item.html_chars,
                outlinks=item.outlinks,
                content_type=item.content_type,
                evidence_scope='validated_fingerprint_exemplars',
                contract_specific=True,
                best_exemplar_url=winner.best_exemplar_url,
                exemplar_score=winner_score,
                exemplar_top_score=winner.top_score,
                exemplar_top3_mean_score=winner.top3_mean_score,
                exemplar_support_count=winner.support_count,
                exemplar_support_ratio=winner.support_ratio,
                exemplar_margin=margin,
                second_contract_name=runner_up.contract_name if runner_up is not None else None,
                positive_exemplar_score=winner.score,
                contrastive_score=contrastive_score if contrastives else None,
                contrastive_weight=contrastive_weight if contrastives else None,
            )
        )

    for contract_name, targets in planned.items():
        ordered = sorted(targets, key=_target_sort_key)
        planned[contract_name] = ordered if max_targets_per_contract is None else ordered[:max_targets_per_contract]

    return FingerprintTargetPlan(
        planned,
        plan_kind='validated_fingerprint_exemplar_ranking',
        evidence_scope='validated_fingerprint_exemplars',
        contract_specific_ranking=True,
        limitations=(
            'Ranking uses explicit validated exemplar URLs per contract; it is not cold-start routing.',
            'URL paths are not used for scoring. qscrape URL labels are only suitable for separate evaluation.',
            'Run verified scrape/discovery before treating any row as extracted-data success.',
        ),
    )


def _score_against_exemplars(
    item: CrawlInventoryItem,
    *,
    contract_name: str,
    exemplars: Sequence[CrawlInventoryItem],
    support_score: float,
) -> _ExemplarScore:
    similarities = [item.fingerprint.similarity(exemplar.fingerprint) for exemplar in exemplars]
    scored = sorted(
        (
            (float(similarity.score), exemplar.url, similarity.same_shape)
            for similarity, exemplar in zip(similarities, exemplars, strict=True)
        ),
        key=lambda row: row[0],
        reverse=True,
    )
    top_score, best_exemplar_url, best_same_shape = scored[0]
    top_n = [score for score, _, _ in scored[: min(3, len(scored))]]
    top3_mean = sum(top_n) / len(top_n)
    support_count = sum(1 for score, _, _ in scored if score >= support_score)
    support_ratio = support_count / len(scored)
    score = (0.60 * top3_mean) + (0.25 * top_score) + (0.15 * support_ratio)
    return _ExemplarScore(
        contract_name=contract_name,
        score=score,
        top_score=top_score,
        top3_mean_score=top3_mean,
        support_count=support_count,
        support_ratio=support_ratio,
        best_exemplar_url=best_exemplar_url,
        best_same_shape=best_same_shape,
    )


@dataclass(frozen=True, slots=True)
class _FingerprintFamily:
    items: tuple[CrawlInventoryItem, ...]
    representative: CrawlInventoryItem
    cohesion_score: float
    item_scores: dict[str, float]


def _fingerprint_families(
    items: list[CrawlInventoryItem], *, family_fingerprint_score: float
) -> list[_FingerprintFamily]:
    candidates = [item for item in items if not item.fingerprint.degenerate]
    if not candidates:
        return []

    parent = list(range(len(candidates)))
    pair_scores: dict[tuple[int, int], float] = {}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for i, left in enumerate(candidates):
        pair_scores[(i, i)] = 1.0
        for j in range(i + 1, len(candidates)):
            right = candidates[j]
            similarity = left.fingerprint.similarity(right.fingerprint)
            score = float(similarity.score)
            pair_scores[(i, j)] = score
            pair_scores[(j, i)] = score
            if similarity.same_shape and score >= family_fingerprint_score:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for index in range(len(candidates)):
        groups.setdefault(find(index), []).append(index)

    families: list[_FingerprintFamily] = []
    for indexes in groups.values():
        family_items = tuple(candidates[index] for index in indexes)
        item_scores_by_index = {
            index: sum(pair_scores[(index, other)] for other in indexes) / len(indexes) for index in indexes
        }
        cohesion = sum(item_scores_by_index.values()) / len(item_scores_by_index)
        representative_index = max(
            indexes,
            key=lambda index: (item_scores_by_index[index], candidates[index].html_chars, -candidates[index].outlinks),
        )
        families.append(
            _FingerprintFamily(
                items=family_items,
                representative=candidates[representative_index],
                cohesion_score=cohesion,
                item_scores={candidates[index].url: item_scores_by_index[index] for index in indexes},
            )
        )
    return sorted(families, key=lambda family: (-len(family.items), -family.cohesion_score, family.representative.url))


def _fingerprint_similarity_rows(inventory: CrawlInventory) -> list[dict[str, Any]]:
    items = list(inventory.items)
    rows: list[dict[str, Any]] = []
    for i, left in enumerate(items):
        for right in items[i:]:
            similarity = left.fingerprint.similarity(right.fingerprint)
            rows.append(
                {
                    'left_url': left.url,
                    'right_url': right.url,
                    'weighted_jaccard_score': round(float(similarity.score), 4),
                    'containment_score': round(float(similarity.containment_score), 4),
                    'same_shape': similarity.same_shape,
                    'skeleton_weighted': round(float(similarity.skeleton.weighted), 4),
                    'semantic_weighted': round(float(similarity.semantic.weighted), 4),
                    'identity_weighted': _optional_weighted(similarity.identity),
                    'ax_weighted': _optional_weighted(similarity.ax),
                    'network_weighted': _optional_weighted(similarity.network),
                    'endpoint_weighted': _optional_weighted(similarity.endpoint),
                }
            )
    return rows


def _optional_weighted(layer: Any) -> float | None:
    if layer is None:
        return None
    return round(float(layer.weighted), 4)


def _diverse_family_order(targets: list[FingerprintTarget]) -> list[FingerprintTarget]:
    """Prefer one target per fingerprint family before filling same-family siblings."""
    by_family: dict[str, list[FingerprintTarget]] = {}
    for target in sorted(targets, key=_target_sort_key):
        by_family.setdefault(target.family_url, []).append(target)

    family_order = sorted(by_family, key=lambda url: _target_sort_key(by_family[url][0]))
    ordered: list[FingerprintTarget] = []
    remaining = True
    while remaining:
        remaining = False
        for family_url in family_order:
            family = by_family[family_url]
            if family:
                ordered.append(family.pop(0))
                remaining = True
    return ordered


def _target_sort_key(target: FingerprintTarget) -> tuple[int, float, float, int, int, str]:
    return (
        -target.family_size,
        -target.score,
        -target.weighted_jaccard_score,
        target.depth,
        target.outlinks,
        target.url,
    )


def _combined_score(
    *,
    fp_score: float,
    family_cohesion: float,
    family_size: int,
    item: CrawlInventoryItem,
) -> float:
    size_score = min(1.0, family_size / 12)
    depth_score = 1.0 / (1 + max(0, item.depth))
    link_penalty = min(0.20, item.outlinks / 500)
    return max(
        0.0,
        (0.50 * family_cohesion) + (0.25 * fp_score) + (0.20 * size_score) + (0.05 * depth_score) - link_penalty,
    )


def _scorable(result: CrawlResult) -> bool:
    if result.status != 'succeeded' or result.fingerprint is None:
        return False
    content_type = (result.content_type or '').split(';', 1)[0].strip().lower()
    return content_type in {'', 'text/html', 'application/xhtml+xml'}


def _contract_allowed_download_types(contract: type[Contract]) -> tuple[str, ...]:
    allowed: list[str] = []
    for cfg in contract.file_fields().values():
        for item in cfg.get('allowed_types') or ():
            if item not in allowed:
                allowed.append(str(item))
    return tuple(allowed)


def _safe_url(url: str, *, include_query_strings: bool) -> str:
    if include_query_strings:
        return url
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, '', ''))


def _target_row(target: FingerprintTarget) -> dict[str, Any]:
    row: dict[str, Any] = {
        'fanout_contract': target.contract_name,
        'url': target.url,
        'family_url': target.family_url,
        'score': round(target.score, 4),
        'weighted_jaccard_score': round(target.weighted_jaccard_score, 4),
        'family_cohesion_score': round(target.family_cohesion_score, 4),
        'same_shape': target.same_shape,
        'neutral_candidate': target.neutral_candidate,
        'evidence_scope': target.evidence_scope,
        'contract_specific': target.contract_specific,
        'verification_status': 'not_verified',
        'family_size': target.family_size,
        'depth': target.depth,
        'html_chars': target.html_chars,
        'outlinks': target.outlinks,
        'content_type': target.content_type,
    }
    if target.exemplar_score is not None:
        row.update(
            {
                'best_exemplar_url': target.best_exemplar_url,
                'exemplar_score': round(target.exemplar_score, 4),
                'exemplar_top_score': _round_optional(target.exemplar_top_score),
                'exemplar_top3_mean_score': _round_optional(target.exemplar_top3_mean_score),
                'exemplar_support_count': target.exemplar_support_count,
                'exemplar_support_ratio': _round_optional(target.exemplar_support_ratio),
                'exemplar_margin': _round_optional(target.exemplar_margin),
                'second_contract': target.second_contract_name,
                'positive_exemplar_score': _round_optional(target.positive_exemplar_score),
                'contrastive_score': _round_optional(target.contrastive_score),
                'contrastive_weight': _round_optional(target.contrastive_weight),
            }
        )
    return row


def _round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


__all__ = [
    'CrawlInventory',
    'CrawlInventoryItem',
    'CrawlTargetWorkflowResult',
    'FingerprintTarget',
    'FingerprintTargetPlan',
    'crawl_contract_targets',
    'plan_contract_targets',
    'scrape_planned_targets',
    'write_target_inventory',
]

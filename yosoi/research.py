"""Local research-frontier packet helpers."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from yosoi.operations import ScrapeResult
from yosoi.utils.files import atomic_write_json, atomic_write_text, init_yosoi

ContractStatus = Literal['candidate', 'validated', 'provisional', 'rejected', 'production']

_POLICY_DIR = Path(__file__).resolve().parents[1] / '.agents' / 'skills' / 'yosoi-research-frontier' / 'assets'
_ZERO_POLICY = _POLICY_DIR / 'frontier-zero-policy.yaml'
_BUDGETED_POLICY = _POLICY_DIR / 'frontier-budgeted-policy.yaml'


class ResearchObservation(BaseModel):
    """One append-only research packet observation."""

    observed_at: str
    kind: Literal['scrape', 'search', 'crawl', 'note']
    artifact: str | None = None
    url: str | None = None
    contract: str | None = None
    contract_fingerprint: str | None = None
    contract_status: ContractStatus = 'candidate'
    scrape_status: str | None = None
    selector_source: str | None = None
    cache_decision: str | None = None
    llm_used: bool | None = None
    quality_status: str | None = None
    quality_issues: list[str] = Field(default_factory=list)
    record_count: int | None = None
    expected_record_count: int | None = None
    summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def _slug(value: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '-', value.strip().lower()).strip('-')
    return cleaned[:64] or 'research'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_text(path: Path, text: str) -> None:
    atomic_write_text(path, text, encoding='utf-8')


def _write_json(path: Path, payload: object) -> None:
    atomic_write_json(path, payload, indent=2)
    _write_text(path, path.read_text(encoding='utf-8') + '\n')


def create_packet(
    topic: str,
    *,
    packet_dir: Path | None = None,
    llm_budget_usd: float = 0.0,
    api_budget_usd: float = 0.0,
) -> Path:
    """Create a local research packet skeleton."""
    now = _now()
    run_id = f'{now.strftime("%Y%m%dT%H%M%SZ")}-{_slug(topic)}'
    root = packet_dir or init_yosoi('research') / run_id
    root.mkdir(parents=True, exist_ok=False)
    for child in ('sources', 'candidate-contracts', 'scrape-results', 'notes'):
        (root / child).mkdir(parents=True, exist_ok=True)

    budgeted = llm_budget_usd > 0 or api_budget_usd > 0
    policy_source = _BUDGETED_POLICY if budgeted else _ZERO_POLICY
    if policy_source.exists():
        shutil.copyfile(policy_source, root / 'policy.yaml')
    else:
        _write_text(root / 'policy.yaml', 'model:\n  require_explicit: true\n')

    _write_json(
        root / 'frontier.json',
        {
            'run_id': run_id,
            'topic': topic,
            'created_at': now.isoformat(),
            'mode': 'budgeted' if budgeted else 'zero-cost',
            'budget': {'llm_usd': llm_budget_usd, 'api_usd': api_budget_usd},
            'status': 'frontier',
        },
    )
    _write_json(
        root / 'query-plan.json',
        {'topic': topic, 'queries': [], 'source_hypotheses': [], 'must_answer': [], 'known_limits': []},
    )
    _write_json(root / 'source-map.json', {'sources': [], 'paid_provider_candidates': [], 'blocked_or_unavailable': []})
    _write_text(root / 'observations.jsonl', '')
    _write_text(root / 'evidence.jsonl', '')
    _write_json(root / 'claims.json', {'claims': []})
    _write_text(
        root / 'brief.md', f'# Research Frontier Brief\n\nTopic: {topic}\n\nDecision this run should support:\n\n- \n'
    )
    _write_text(root / 'limitations.md', '# Limitations\n\n- Unknown until source survey is complete.\n')
    _write_text(
        root / 'mvp-plan.md', '# MVP Plan\n\n- Smallest useful deliverable:\n- Data sources:\n- Manual checks:\n'
    )
    _write_text(
        root / 'pipeline-plan.md',
        '# Production Pipeline Plan\n\n'
        '- Deterministic sources:\n'
        '- Yosoi contracts to promote:\n'
        '- Schedule:\n'
        '- Storage/index needs:\n'
        '- LLM/API work removed from hot path:\n',
    )
    _write_text(
        root / 'commands.md',
        '# Commands\n\n'
        '```bash\n'
        f'UV_CACHE_DIR=/tmp/uv-cache uv run yosoi search "{topic}" --limit 10 --json > {root}/sources/search-001.json\n'
        f'UV_CACHE_DIR=/tmp/uv-cache uv run yosoi crawl "SEED_URL" --limit 20 --json --policy {root}/policy.yaml > {root}/sources/crawl-001.json\n'
        f'UV_CACHE_DIR=/tmp/uv-cache uv run yosoi scrape "URL" --json --policy {root}/policy.yaml > {root}/scrape-results/scrape-001.json\n'
        '```\n',
    )
    return root


def append_observations(packet: Path, observations: list[ResearchObservation]) -> Path:
    """Append observations to a packet JSONL file."""
    packet = packet.resolve()
    if not (packet / 'frontier.json').exists():
        raise ValueError(f'{packet} is not a research packet')
    path = packet / 'observations.jsonl'
    with path.open('a', encoding='utf-8') as handle:
        for observation in observations:
            handle.write(observation.model_dump_json(exclude_none=True) + '\n')
    return path


def observations_from_scrape(path: Path, *, contract_status: ContractStatus | None = None) -> list[ResearchObservation]:
    """Build research observations from a canonical ScrapeResult JSON artifact."""
    payload = json.loads(path.read_text(encoding='utf-8'))
    result = ScrapeResult.model_validate(payload)
    out: list[ResearchObservation] = []
    now = _now().isoformat()
    for unit in result.results:
        status = contract_status or _status_from_scrape_unit(unit.model_dump())
        out.append(
            ResearchObservation(
                observed_at=now,
                kind='scrape',
                artifact=str(path),
                url=unit.url,
                contract=unit.contract,
                contract_fingerprint=unit.contract_fingerprint,
                contract_status=status,
                scrape_status=unit.status,
                selector_source=unit.selector_source,
                cache_decision=unit.cache_decision,
                llm_used=unit.llm_used,
                quality_status=unit.quality_status,
                quality_issues=unit.quality_issues,
                record_count=unit.record_count,
                expected_record_count=unit.expected_record_count,
                payload={'error': unit.error} if unit.error else {},
            )
        )
    return out


def observation_from_artifact(
    kind: Literal['search', 'crawl'],
    path: Path,
    *,
    contract_status: ContractStatus = 'candidate',
) -> ResearchObservation:
    """Build a summary observation from a search or crawl JSON artifact."""
    payload = json.loads(path.read_text(encoding='utf-8'))
    count = 0
    if kind == 'search' and isinstance(payload, dict):
        count = len(payload.get('hits') or payload.get('urls') or [])
    elif kind == 'crawl' and isinstance(payload, dict):
        summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else payload
        assert isinstance(summary, dict)
        count = int(summary.get('pages_fetched') or len(summary.get('results') or []))
    return ResearchObservation(
        observed_at=_now().isoformat(),
        kind=kind,
        artifact=str(path),
        contract_status=contract_status,
        summary=f'{kind} artifact with {count} observed item(s)',
        payload={'observed_count': count},
    )


def observation_from_note(note: str, *, contract_status: ContractStatus = 'candidate') -> ResearchObservation:
    """Build a free-form note observation."""
    return ResearchObservation(
        observed_at=_now().isoformat(),
        kind='note',
        contract_status=contract_status,
        summary=note,
    )


def summarize_packet(packet: Path) -> dict[str, Any]:
    """Summarize contract statuses and open quality gaps for a packet."""
    packet = packet.resolve()
    meta = json.loads((packet / 'frontier.json').read_text(encoding='utf-8'))
    observations = _read_observations(packet / 'observations.jsonl')
    contracts: dict[str, dict[str, Any]] = {}
    latest_by_scope: dict[tuple[str, str], ResearchObservation] = {}
    latest: list[dict[str, Any]] = []
    for obs in observations:
        latest.append(obs.model_dump(exclude_none=True))
        key = obs.contract or '(unscoped)'
        scope = obs.url or obs.artifact or obs.summary or ''
        latest_by_scope[(key, scope)] = obs
        entry = contracts.setdefault(
            key,
            {
                'status': 'candidate',
                'observations': 0,
                'latest_artifact': None,
                'latest_quality_status': None,
                'latest_record_count': None,
            },
        )
        entry['observations'] += 1
        entry['status'] = _merge_status(str(entry['status']), obs.contract_status)
        entry['latest_artifact'] = obs.artifact or entry['latest_artifact']
        entry['latest_quality_status'] = obs.quality_status or entry['latest_quality_status']
        entry['latest_record_count'] = (
            obs.record_count if obs.record_count is not None else entry['latest_record_count']
        )
    gaps: list[str] = []
    for (key, scope), obs in latest_by_scope.items():
        if obs.quality_status == 'ok' and not obs.quality_issues:
            continue
        for issue in obs.quality_issues:
            target = f'{key} ({scope})' if scope else key
            gaps.append(f'{target}: {issue}')
    return {
        'packet': str(packet),
        'topic': meta.get('topic'),
        'run_id': meta.get('run_id'),
        'contracts': contracts,
        'latest': latest[-10:],
        'open_quality_gaps': gaps,
    }


def _read_observations(path: Path) -> list[ResearchObservation]:
    if not path.exists():
        return []
    return [
        ResearchObservation.model_validate_json(line)
        for line in path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]


def _status_from_scrape_unit(unit: dict[str, Any]) -> ContractStatus:
    if unit.get('status') == 'failed' or unit.get('quality_status') == 'failed':
        return 'rejected'
    if (
        unit.get('status') == 'ok'
        and unit.get('quality_status') == 'ok'
        and unit.get('selector_source') in {'cache', 'atom_cache'}
        and unit.get('llm_used') is False
        and unit.get('expected_record_count') is not None
    ):
        return 'validated'
    if unit.get('status') == 'ok':
        return 'provisional'
    return 'candidate'


def _merge_status(current: str, new: str) -> ContractStatus:
    order = {'rejected': 0, 'candidate': 1, 'provisional': 2, 'validated': 3, 'production': 4}
    if current == 'rejected' and new != 'production':
        return 'rejected'
    return cast('ContractStatus', max((current, new), key=lambda status: order.get(status, 1)))

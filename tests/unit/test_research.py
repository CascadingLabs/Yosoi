"""Tests for local research packet helpers."""

from pathlib import Path

import pytest

import yosoi.research as research
from yosoi.operations import ScrapeResult, ScrapeUnitResult
from yosoi.research import (
    _merge_status,
    _status_from_scrape_unit,
    append_observations,
    create_packet,
    observation_from_artifact,
    observation_from_note,
    observations_from_scrape,
    summarize_packet,
)


def test_observations_from_search_and_crawl_artifacts(tmp_path: Path) -> None:
    search_path = tmp_path / 'search.json'
    search_path.write_text('{"hits": [{"url": "https://one.test"}, {"url": "https://two.test"}]}', encoding='utf-8')
    crawl_path = tmp_path / 'crawl.json'
    crawl_path.write_text('{"summary": {"pages_fetched": 3, "results": []}}', encoding='utf-8')
    crawl_without_summary_path = tmp_path / 'crawl-without-summary.json'
    crawl_without_summary_path.write_text('{"results": [{"url": "https://one.test"}]}', encoding='utf-8')

    search = observation_from_artifact('search', search_path)
    crawl = observation_from_artifact('crawl', crawl_path, contract_status='provisional')
    crawl_without_summary = observation_from_artifact('crawl', crawl_without_summary_path)

    assert search.payload['observed_count'] == 2
    assert crawl.payload['observed_count'] == 3
    assert crawl_without_summary.payload['observed_count'] == 1
    assert crawl.contract_status == 'provisional'


def test_observation_from_note() -> None:
    observation = observation_from_note('robots blocks crawl', contract_status='rejected')

    assert observation.kind == 'note'
    assert observation.contract_status == 'rejected'
    assert observation.summary == 'robots blocks crawl'


def test_append_observations_rejects_non_packet(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not a research packet'):
        append_observations(tmp_path, [observation_from_note('no packet')])


def test_scrape_observation_status_rules(tmp_path: Path) -> None:
    scrape_path = tmp_path / 'scrape.json'
    scrape_path.write_text(
        ScrapeResult(
            results=[
                ScrapeUnitResult(
                    url='https://one.test',
                    contract='PricingPlan',
                    contract_fingerprint='fp',
                    selector_source='discovery',
                    cache_decision='miss',
                    llm_used=True,
                    quality_status='ok',
                    record_count=4,
                    records=[{'name': 'Free'}],
                ),
                ScrapeUnitResult(
                    url='https://two.test',
                    contract='BrokenPlan',
                    contract_fingerprint='broken-fp',
                    status='failed',
                    quality_status='failed',
                    error='required field missing',
                ),
            ]
        ).model_dump_json(),
        encoding='utf-8',
    )

    observations = observations_from_scrape(scrape_path)

    assert [observation.contract_status for observation in observations] == ['provisional', 'rejected']
    assert observations[1].payload == {'error': 'required field missing'}


def test_summarize_packet_keeps_rejected_until_production_override(tmp_path: Path) -> None:
    packet = create_packet('pricing research', packet_dir=tmp_path / 'packet')
    append_observations(
        packet,
        [
            observation_from_note('first candidate', contract_status='candidate'),
            observation_from_note('blocked source', contract_status='rejected'),
            observation_from_note('manual production override', contract_status='production'),
        ],
    )

    summary = summarize_packet(packet)

    assert summary['contracts']['(unscoped)']['status'] == 'production'
    assert len(summary['latest']) == 3


def test_create_packet_writes_default_policy_when_asset_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(research, '_ZERO_POLICY', tmp_path / 'missing-zero-policy.yaml')

    packet = create_packet('missing policy asset', packet_dir=tmp_path / 'packet')

    assert (packet / 'policy.yaml').read_text(encoding='utf-8') == 'model:\n  require_explicit: true\n'


def test_summarize_packet_reports_quality_gaps_and_missing_observations(tmp_path: Path) -> None:
    packet = create_packet('quality gaps', packet_dir=tmp_path / 'packet')
    (packet / 'observations.jsonl').unlink()

    empty_summary = summarize_packet(packet)

    assert empty_summary['contracts'] == {}
    append_observations(
        packet,
        [
            research.ResearchObservation(
                observed_at='2026-06-27T00:00:00+00:00',
                kind='scrape',
                contract='PricingPlan',
                contract_status='provisional',
                quality_status='partial',
                quality_issues=['record count dropped below discovery baseline'],
                record_count=3,
                expected_record_count=4,
            )
        ],
    )

    summary = summarize_packet(packet)

    assert summary['open_quality_gaps'] == ['PricingPlan: record count dropped below discovery baseline']
    assert summary['contracts']['PricingPlan']['latest_quality_status'] == 'partial'
    assert summary['contracts']['PricingPlan']['latest_record_count'] == 3


def test_summarize_packet_only_reports_latest_gap_per_contract_scope(tmp_path: Path) -> None:
    packet = create_packet('quality gap lifecycle', packet_dir=tmp_path / 'packet')

    append_observations(
        packet,
        [
            research.ResearchObservation(
                observed_at='2026-06-27T00:00:00+00:00',
                kind='scrape',
                contract='PricingPlan',
                contract_status='rejected',
                url='https://one.test/pricing',
                quality_status='failed',
                quality_issues=['cache miss'],
            ),
            research.ResearchObservation(
                observed_at='2026-06-27T00:01:00+00:00',
                kind='scrape',
                contract='PricingPlan',
                contract_status='validated',
                url='https://one.test/pricing',
                quality_status='ok',
            ),
            research.ResearchObservation(
                observed_at='2026-06-27T00:02:00+00:00',
                kind='scrape',
                contract='PricingPlan',
                contract_status='rejected',
                url='https://two.test/pricing',
                quality_status='failed',
                quality_issues=['cache miss'],
            ),
        ],
    )

    summary = summarize_packet(packet)

    assert summary['open_quality_gaps'] == ['PricingPlan (https://two.test/pricing): cache miss']


def test_private_status_helpers_keep_rejected_sticky_until_production() -> None:
    assert _status_from_scrape_unit({}) == 'candidate'
    assert _merge_status('rejected', 'validated') == 'rejected'
    assert _merge_status('rejected', 'production') == 'production'

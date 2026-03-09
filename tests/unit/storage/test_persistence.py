"""Tests for SelectorStorage save/load/domain extraction."""

import pytest

from yosoi.storage.persistence import SelectorStorage


@pytest.fixture
def storage(tmp_path, mocker):
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    return SelectorStorage()


def test_save_and_load_selectors(storage):
    selectors = {
        'headline': {'primary': 'h1.title', 'fallback': 'h1', 'tertiary': 'NA'},
    }
    storage.save_selectors('https://example.com/article', selectors)
    loaded = storage.load_selectors('example.com')
    assert loaded is not None
    assert loaded['headline']['primary'] == 'h1.title'


def test_nonexistent_domain_returns_none(storage):
    result = storage.load_selectors('nonexistent.com')
    assert result is None


def test_domain_extraction_strips_www(storage):
    domain = storage._extract_domain('https://www.example.com/path')
    assert domain == 'example.com'


def test_domain_extraction_no_www(storage):
    domain = storage._extract_domain('https://example.com/path')
    assert domain == 'example.com'


def test_selector_exists_after_save(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://test.com', selectors)
    assert storage.selector_exists('test.com') is True


def test_selector_not_exists(storage):
    assert storage.selector_exists('nothere.com') is False


def test_list_domains_empty(storage):
    assert storage.list_domains() == []


def test_list_domains_after_save(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://alpha.com', selectors)
    storage.save_selectors('https://beta.com', selectors)
    domains = storage.list_domains()
    assert 'alpha.com' in domains
    assert 'beta.com' in domains


def test_get_summary_total_domains(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    summary = storage.get_summary()
    assert summary['total_domains'] == 1
    assert len(summary['domains']) == 1


def test_get_summary_empty(storage):
    summary = storage.get_summary()
    assert summary['total_domains'] == 0
    assert summary['domains'] == []


def test_load_selectors_returns_none_for_missing(storage):
    assert storage.load_selectors('missing.com') is None

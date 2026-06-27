from __future__ import annotations

import json
from pathlib import Path

import pytest

from yosoi.policy import Policy
from yosoi.policy.files import (
    POLICY_SCHEMA_URL,
    PolicyFileError,
    dump_policy,
    dump_policy_schema,
    init_policy_files,
    load_policy_directory,
    load_policy_file,
    load_policy_layers,
    load_policy_source,
    policy_init_document,
    policy_json_schema,
)


def test_load_policy_file_supports_yaml_and_json(tmp_path):
    yaml_file = tmp_path / 'policy.yaml'
    json_file = tmp_path / 'policy.json'
    yaml_file.write_text('atom_reads: true\ntrust_tier: yellow\noutput:\n  formats: [jsonl]\n', encoding='utf-8')
    json_file.write_text(json.dumps({'scrape': {'fetcher_type': 'headless'}}), encoding='utf-8')

    yaml_policy = load_policy_file(yaml_file)
    json_policy = load_policy_file(json_file)

    assert yaml_policy.atom_reads is True
    assert yaml_policy.trust_tier == 'yellow'
    assert yaml_policy.output is not None
    assert yaml_policy.output.formats == ('jsonl',)
    assert json_policy.scrape is not None
    assert json_policy.scrape.fetcher_type == 'headless'


def test_load_policy_source_supports_inline_yaml_and_json():
    inline_yaml = load_policy_source('atom_reads: true\npage:\n  fetcher_type: simple\n')
    inline_json = load_policy_source('{"output": {"flat_files": true}}')

    assert inline_yaml.atom_reads is True
    assert inline_yaml.page is not None
    assert inline_yaml.page.fetcher_type == 'simple'
    assert inline_json.output is not None
    assert inline_json.output.flat_files is True


def test_policy_files_reject_wasted_namespace_wrapper():
    with pytest.raises(PolicyFileError, match='remove namespace'):
        load_policy_source('yosoi:\n  policy:\n    atom_reads: true\n')


def test_load_policy_layers_discovers_global_project_and_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'repo').mkdir()
    monkeypatch.chdir(tmp_path / 'repo')
    (tmp_path / 'home' / '.config' / 'yosoi' / 'policy').mkdir(parents=True)
    (tmp_path / 'repo' / '.yosoi' / 'policy').mkdir(parents=True)
    (tmp_path / 'home' / '.config' / 'yosoi' / 'policy.yaml').write_text('atom_reads: true\n', encoding='utf-8')
    (tmp_path / 'home' / '.config' / 'yosoi' / 'policy' / '10-output.yaml').write_text(
        'output:\n  flat_files: true\n', encoding='utf-8'
    )
    (tmp_path / 'repo' / '.yosoi' / 'policy.json').write_text(
        json.dumps({'output': {'formats': ['jsonl']}}), encoding='utf-8'
    )
    (tmp_path / 'repo' / '.yosoi' / 'policy' / '00-page.yaml').write_text(
        'page:\n  fetcher_type: simple\n', encoding='utf-8'
    )
    (tmp_path / 'repo' / '.yosoi' / 'policy' / 'README.md').write_text('ignore me', encoding='utf-8')

    policy = load_policy_layers(('output:\n  flat_files: false\n',))

    assert policy.atom_reads is True
    assert policy.output is not None
    assert policy.output.formats == ('jsonl',)
    assert policy.output.flat_files is False
    assert policy.page is not None
    assert policy.page.fetcher_type == 'simple'


def test_policy_directory_loads_recursive_children_lexicographically(tmp_path):
    policy_dir = tmp_path / 'policy'
    nested = policy_dir / '20-nested'
    nested.mkdir(parents=True)
    (policy_dir / '10-output.yaml').write_text('output:\n  flat_files: true\n', encoding='utf-8')
    (nested / '00-output.yaml').write_text('output:\n  flat_files: false\n', encoding='utf-8')
    (policy_dir / '30-atom.json').write_text(json.dumps({'atom_reads': True}), encoding='utf-8')
    (nested / 'ignored.txt').write_text('not_a_policy_key: true', encoding='utf-8')

    policy = load_policy_directory(policy_dir)

    assert policy.output is not None
    assert policy.output.flat_files is False
    assert policy.atom_reads is True


def test_dump_policy_supports_yaml():
    dumped = dump_policy(Policy(atom_reads=True), fmt='yaml')

    assert 'atom_reads: true' in dumped


def test_policy_schema_and_init_document_are_editor_ready():
    schema = policy_json_schema()
    dumped_schema = json.loads(dump_policy_schema())
    document = policy_init_document()

    assert schema['$id'] == POLICY_SCHEMA_URL
    assert schema['additionalProperties'] is False
    assert dumped_schema['properties']['atom_reads']['default'] is False
    assert f'# yaml-language-server: $schema={POLICY_SCHEMA_URL}' in document
    assert load_policy_source(document).trust_tier == 'strict'


def test_init_policy_files_writes_global_and_local(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'repo').mkdir()
    monkeypatch.chdir(tmp_path / 'repo')

    written = init_policy_files(global_config=True, local_config=True)

    assert written == (
        tmp_path / 'home' / '.config' / 'yosoi' / 'policy.yaml',
        Path('.yosoi') / 'policy.yaml',
    )
    for path in written:
        assert path.read_text(encoding='utf-8').startswith('# yaml-language-server: $schema=')
    with pytest.raises(PolicyFileError, match='already exists'):
        init_policy_files(local_config=True)


def test_policy_file_error_paths(tmp_path):
    missing = tmp_path / 'missing.yaml'
    bad_json = tmp_path / 'bad.json'
    bad_yaml = tmp_path / 'bad.yaml'
    unsupported = tmp_path / 'policy.toml'

    bad_json.write_text('{bad json', encoding='utf-8')
    bad_yaml.write_text('field: [unterminated', encoding='utf-8')
    unsupported.write_text('atom_reads = true', encoding='utf-8')

    with pytest.raises(PolicyFileError, match='Cannot read policy file'):
        load_policy_file(missing)
    with pytest.raises(PolicyFileError, match='Invalid JSON policy'):
        load_policy_file(bad_json)
    with pytest.raises(PolicyFileError, match='Invalid YAML policy'):
        load_policy_file(bad_yaml)
    with pytest.raises(PolicyFileError, match='Unsupported policy file extension'):
        load_policy_file(unsupported)
    with pytest.raises(PolicyFileError, match='must be a JSON/YAML object'):
        load_policy_source('[1, 2, 3]')
    with pytest.raises(PolicyFileError, match='Unknown top-level policy key'):
        load_policy_source('not_a_policy_key: true')
    with pytest.raises(PolicyFileError, match='Invalid policy'):
        load_policy_source('trust_tier: blue')
    with pytest.raises(ValueError, match='Unsupported policy format'):
        dump_policy(Policy(), fmt='toml')  # type: ignore[arg-type]

from __future__ import annotations

import pytest

import yosoi as ys
from yosoi.executor import JavaScriptModules, bind_executor_action


def test_javascript_modules_bundle_static_relative_named_imports(tmp_path) -> None:
    (tmp_path / 'helper.mjs').write_text('export function double(value) { return value * 2; }')
    (tmp_path / 'entry.mjs').write_text(
        "import {double} from './helper.mjs';\nexport function run({value}) { return double(value); }"
    )

    function = JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    assert 'function double' in function.expression
    assert 'function run' in function.expression
    assert 'import ' not in function.expression
    assert function.fingerprint == JavaScriptModules(tmp_path).function('entry.mjs', export='run').fingerprint


def test_executor_settle_rejects_invalid_timing() -> None:
    with pytest.raises(ValueError, match='timeout must be >= 0'):
        ys.until.non_null(timeout=-1)
    with pytest.raises(ValueError, match='poll_interval must be > 0'):
        ys.until.length_at_least(1, poll_interval=0)


def test_javascript_modules_reject_root_escape(tmp_path) -> None:
    outside = tmp_path.parent / 'outside.mjs'
    outside.write_text('export function run() { return true; }')

    with pytest.raises(ValueError, match='escapes configured root'):
        JavaScriptModules(tmp_path).function('../outside.mjs', export='run')


def test_executor_js_binds_literal_args_for_inline_contract_function() -> None:
    class Page(ys.Contract):
        count: int = ys.Executor.js('(args) => args.count', args={'count': 4})

    config = Page.action_fields()['count']
    assert config['script'] == '((args) => args.count)({"count":4})'


def test_executor_js_static_contract_field_uses_existing_action_metadata(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text('export function title(_args) { return document.title; }')
    function = ys.Executor.js.modules(tmp_path).function('entry.mjs', export='title')

    class Page(ys.Contract):
        title: str = ys.Executor.js(function)

    config = Page.action_fields()['title']
    assert config['type'] == 'js'
    assert config['module'] == 'entry.mjs'
    assert function.fingerprint == config['fingerprint']
    assert 'document.title' in config['script']


def test_executor_js_rejects_flow_inputs_on_contract_fields(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text('export function take({limit}) { return [limit]; }')
    function = ys.Executor.js.modules(tmp_path).function('entry.mjs', export='take')

    with pytest.raises(TypeError, match=r'runtime inputs are valid only on ys\.Flow'):

        class InvalidPage(ys.Contract):
            values: list[int] = ys.Executor.js(function, args={'limit': ys.input('limit')})


def test_executor_js_runtime_inputs_bind_without_source_interpolation(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text('export function take({limit}) { return [limit]; }')
    function = ys.Executor.js.modules(tmp_path).function('entry.mjs', export='take')
    field = ys.Executor.js(function, args={'limit': ys.input('limit')})
    extra = field.json_schema_extra
    assert isinstance(extra, dict)
    config = extra['yosoi_action']

    script = bind_executor_action(config, {'limit': 7})

    assert script.endswith('({"limit":7})')
    with pytest.raises(ValueError, match='missing required Flow input'):
        bind_executor_action(config, {})

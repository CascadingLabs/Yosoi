from __future__ import annotations

import json
import shutil
import subprocess

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


def test_javascript_modules_preserve_private_scope_across_modules(tmp_path) -> None:
    (tmp_path / 'left.mjs').write_text(
        'const normalize = value => `left:${value}`;\nexport function fromLeft(value) { return normalize(value); }'
    )
    (tmp_path / 'right.mjs').write_text(
        'function normalize(value) { return `right:${value}`; }\n'
        'export function fromRight(value) { return normalize(value); }'
    )
    (tmp_path / 'entry.mjs').write_text(
        "import {fromLeft} from './left.mjs';\n"
        "import {fromRight} from './right.mjs';\n"
        'export function run({value}) { return [fromLeft(value), fromRight(value)]; }'
    )

    function = JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    assert function.expression.count('(function () {') == 3
    assert function.expression.count('normalize') == 4
    node = shutil.which('node')
    if node is not None:
        completed = subprocess.run(
            [node],
            input=f"const fn = {function.expression}; console.log(JSON.stringify(fn({{value: 'x'}})));",
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(completed.stdout) == ['left:x', 'right:x']


def test_javascript_modules_reject_invalid_syntax_before_browser_execution(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text('export function run( { return true; }')

    with pytest.raises(ValueError, match=r'invalid JavaScript syntax in entry\.mjs:1:'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')


def test_javascript_modules_reject_cycles_with_graph_path(tmp_path) -> None:
    (tmp_path / 'left.mjs').write_text("import {right} from './right.mjs';\nexport function left() { return right(); }")
    (tmp_path / 'right.mjs').write_text("import {left} from './left.mjs';\nexport function right() { return left(); }")

    with pytest.raises(ValueError, match=r'left\.mjs -> right\.mjs -> left\.mjs'):
        JavaScriptModules(tmp_path).function('left.mjs', export='left')


def test_javascript_modules_reject_runtime_module_syntax(tmp_path) -> None:
    unsupported = (
        "export function run() { return import('./other.mjs'); }",
        'export function run() { return import.meta.url; }',
        'await Promise.resolve(); export function run() { return true; }',
        'for await (const value of values) {} export function run() { return true; }',
        'return; export function run() { return true; }',
        'export function run(value) { with (value) { return true; } }',
    )

    for source in unsupported:
        (tmp_path / 'entry.mjs').write_text(source)
        with pytest.raises(ValueError, match='unsupported JavaScript import/export syntax'):
            JavaScriptModules(tmp_path).function('entry.mjs', export='run')


def test_javascript_modules_reexports_names_without_object_prototype_collisions(tmp_path) -> None:
    (tmp_path / 'helper.mjs').write_text("export function __proto__() { return 'safe'; }")
    (tmp_path / 'entry.mjs').write_text("export {__proto__} from './helper.mjs';")

    function = JavaScriptModules(tmp_path).function('entry.mjs', export='__proto__')

    assert '["__proto__"]' in function.expression
    node = shutil.which('node')
    if node is not None:
        completed = subprocess.run(
            [node],
            input=f'const fn = {function.expression}; console.log(fn({{}}));',
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stdout.strip() == 'safe'


def test_javascript_modules_reject_non_utf8_source(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_bytes(b'export function run() {}\n\xff')

    with pytest.raises(ValueError, match='module is not valid UTF-8'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')


def test_javascript_modules_reject_mutable_or_non_callable_entry_exports(tmp_path) -> None:
    (tmp_path / 'mutable.mjs').write_text('export let run = () => true;')
    with pytest.raises(ValueError, match='mutable live binding'):
        JavaScriptModules(tmp_path).function('mutable.mjs', export='run')

    (tmp_path / 'value.mjs').write_text('export const run = 42;')
    with pytest.raises(ValueError, match="export 'run' is not statically callable"):
        JavaScriptModules(tmp_path).function('value.mjs', export='run')


def test_javascript_modules_ignore_module_syntax_inside_comments_and_templates(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text(
        "// import {missing} from './missing.mjs';\n"
        "export function run() { return `export {missing} from './missing.mjs'`; }"
    )

    function = JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    assert "export {missing} from './missing.mjs'" in function.expression


def test_executor_settle_rejects_invalid_timing() -> None:
    with pytest.raises(ValueError, match='timeout must be >= 0'):
        ys.until.non_null(timeout=-1)
    with pytest.raises(ValueError, match='poll_interval must be > 0'):
        ys.until.length_at_least(1, poll_interval=0)
    with pytest.raises(ValueError, match='timeout must be a finite number'):
        ys.until.non_null(timeout=float('nan'))
    with pytest.raises(ValueError, match='poll_interval must be a finite number'):
        ys.until.non_null(poll_interval=float('inf'))
    with pytest.raises(TypeError, match='length_at_least must be an integer'):
        ys.until.length_at_least(1.5)  # type: ignore[arg-type]


def test_javascript_modules_reject_root_escape(tmp_path) -> None:
    outside = tmp_path.parent / 'outside.mjs'
    outside.write_text('export function run() { return true; }')

    with pytest.raises(ValueError, match='escapes configured root'):
        JavaScriptModules(tmp_path).function('../outside.mjs', export='run')


def test_javascript_modules_reject_oversized_entry_before_parsing(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text('export function run() {}\n' + 'x' * 512_000)

    with pytest.raises(ValueError, match='module exceeds 512000 bytes'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')


def test_javascript_modules_rejects_non_exported_entry_function(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text(
        'function privateHelper() { return 1; }\nexport function run() { return privateHelper(); }'
    )

    with pytest.raises(ValueError, match="export 'privateHelper' was not found"):
        JavaScriptModules(tmp_path).function('entry.mjs', export='privateHelper')


def test_javascript_modules_do_not_treat_comments_as_exports(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text(
        '// export function privateHelper() {}\n'
        'function privateHelper() { return 1; }\n'
        'export function run() { return privateHelper(); }'
    )

    with pytest.raises(ValueError, match="export 'privateHelper' was not found"):
        JavaScriptModules(tmp_path).function('entry.mjs', export='privateHelper')


def test_javascript_modules_preserve_export_text_inside_string_literals(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text('export function run() { return "export function is documentation"; }')

    function = JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    assert '"export function is documentation"' in function.expression


def test_javascript_modules_reject_unsupported_static_module_forms(tmp_path) -> None:
    (tmp_path / 'helper.mjs').write_text('export function helper() { return true; }')
    unsupported = (
        "import './helper.mjs';\nexport function run() { return true; }",
        "import helper from './helper.mjs';\nexport function run() { return helper(); }",
        "import * as helpers from './helper.mjs';\nexport function run() { return helpers.helper(); }",
        'export default function run() { return true; }',
    )

    for source in unsupported:
        (tmp_path / 'entry.mjs').write_text(source)
        with pytest.raises(ValueError, match='unsupported JavaScript import/export syntax'):
            JavaScriptModules(tmp_path).function('entry.mjs', export='run')


def test_javascript_modules_reject_large_module_graphs(tmp_path) -> None:
    for index in range(129):
        dependency = f"import {{step{index + 1}}} from './step{index + 1}.mjs';\n" if index < 128 else ''
        (tmp_path / f'step{index}.mjs').write_text(f'{dependency}export function step{index}() {{ return {index}; }}')

    with pytest.raises(ValueError, match='module graph exceeds 128 files'):
        JavaScriptModules(tmp_path).function('step0.mjs', export='step0')


def test_javascript_modules_rejects_named_import_aliases_before_browser_execution(tmp_path) -> None:
    (tmp_path / 'helper.mjs').write_text('export function original() { return 1; }')
    (tmp_path / 'entry.mjs').write_text(
        "import {original as renamed} from './helper.mjs';\nexport function run() { return renamed(); }"
    )

    with pytest.raises(ValueError, match='aliases are not supported'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')


def test_javascript_modules_rejects_missing_imported_export(tmp_path) -> None:
    (tmp_path / 'helper.mjs').write_text('export function available() { return 1; }')
    (tmp_path / 'entry.mjs').write_text(
        "import {missing} from './helper.mjs';\nexport function run() { return missing(); }"
    )

    with pytest.raises(ValueError, match="export 'missing' was not found"):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')


def test_javascript_modules_link_local_exports_aliases_and_destructuring(tmp_path) -> None:
    (tmp_path / 'helper.mjs').write_text('export function helper({value}) { return value * 2; }')
    (tmp_path / 'entry.mjs').write_text(
        "import {helper} from './helper';\nconst {value: unused} = {value: 1};\nconst run = helper;\nexport {run};"
    )

    function = JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    assert 'const run = helper' in function.expression
    assert 'const {value: unused}' in function.expression
    node = shutil.which('node')
    if node is not None:
        completed = subprocess.run(
            [node],
            input=f'const fn = {function.expression}; console.log(fn({{value: 4}}));',
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stdout.strip() == '8'


def test_javascript_modules_emit_shared_dependencies_once(tmp_path) -> None:
    (tmp_path / 'shared.mjs').write_text('export const value = 1;')
    (tmp_path / 'left.mjs').write_text("import {value} from './shared.mjs';\nexport function left() { return value; }")
    (tmp_path / 'right.mjs').write_text(
        "import {value} from './shared.mjs';\nexport function right() { return value; }"
    )
    (tmp_path / 'entry.mjs').write_text(
        "import {left} from './left.mjs';\n"
        "import {right} from './right.mjs';\n"
        'export function run() { return left() + right(); }'
    )

    function = JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    assert function.expression.count('// module: "shared.mjs"') == 1


def test_javascript_modules_reject_undeclared_local_and_reexported_names(tmp_path) -> None:
    (tmp_path / 'local.mjs').write_text('export {missing};')
    with pytest.raises(ValueError, match="export 'missing' references an undeclared binding"):
        JavaScriptModules(tmp_path).function('local.mjs', export='missing')

    (tmp_path / 'helper.mjs').write_text('export function available() {}')
    (tmp_path / 'reexport.mjs').write_text("export {missing} from './helper.mjs';")
    with pytest.raises(ValueError, match="export 'missing' was not found in its re-exported module"):
        JavaScriptModules(tmp_path).function('reexport.mjs', export='missing')


def test_javascript_modules_reject_duplicate_bindings_and_exports(tmp_path) -> None:
    (tmp_path / 'binding.mjs').write_text('const run = () => 1; function run() {} export {run};')
    with pytest.raises(ValueError, match="duplicate JavaScript binding 'run'"):
        JavaScriptModules(tmp_path).function('binding.mjs', export='run')

    (tmp_path / 'export.mjs').write_text('function run() {} export {run}; export {run};')
    with pytest.raises(ValueError, match="duplicate JavaScript export 'run'"):
        JavaScriptModules(tmp_path).function('export.mjs', export='run')


def test_javascript_modules_reject_invalid_resolution_and_specifiers(tmp_path) -> None:
    (tmp_path / 'entry.mjs').write_text("import {helper} from 'package';\nexport function run() { return helper(); }")
    with pytest.raises(ValueError, match='only relative JavaScript imports are supported'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    (tmp_path / 'entry.mjs').write_text(
        "import {helper} from './hel\\u0070er.mjs';\nexport function run() { return helper(); }"
    )
    with pytest.raises(ValueError, match='unsupported JavaScript module specifier'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')

    with pytest.raises(ValueError, match=r'modules must use \.js or \.mjs'):
        JavaScriptModules(tmp_path).function('entry.txt', export='run')
    with pytest.raises(ValueError, match='module does not exist'):
        JavaScriptModules(tmp_path).function('missing.mjs', export='run')
    with pytest.raises(ValueError, match='invalid JavaScript export name'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='not-valid')


def test_javascript_modules_reject_linked_output_limit(tmp_path, mocker) -> None:
    (tmp_path / 'entry.mjs').write_text('export function run() { return true; }')
    mocker.patch('yosoi._javascript_modules._MAX_GRAPH_BYTES', 100)

    with pytest.raises(ValueError, match='linked JavaScript bundle exceeds 100 bytes'):
        JavaScriptModules(tmp_path).function('entry.mjs', export='run')


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


def test_executor_js_rejects_flow_settle_timing_on_contract_fields() -> None:
    with pytest.raises(TypeError, match=r'settle conditions are valid only on ys\.Flow'):

        class InvalidPage(ys.Contract):
            title: str = ys.Executor.js(
                'document.title',
                settle=ys.until.non_null(timeout=1),
            )


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

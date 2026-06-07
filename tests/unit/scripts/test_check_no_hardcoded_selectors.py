from pathlib import Path

import pytest

from scripts.check_no_hardcoded_selectors import check_files, main


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / 'example.py'
    path.write_text(source)
    return path


def test_allows_contract_without_selectors(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
import yosoi as ys

class Product(ys.Contract):
    name: str = ys.Title(description='Product name')
""",
    )

    assert check_files([path]) == []


def test_rejects_selector_literal_inside_unresolved_call(tmp_path: Path) -> None:
    path = _write(tmp_path, "factory['css']('.product-card')\n")

    violations = check_files([path])

    assert violations
    assert 'selector-looking string literal' in violations[0].reason


def test_allows_annotated_root_without_value(tmp_path: Path) -> None:
    path = _write(tmp_path, 'root: str\n')

    assert check_files([path]) == []


def test_rejects_root_selector_factory(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
import yosoi as ys

class Product(ys.Contract):
    root = ys.css('.product-card')
    name: str = ys.Title(description='Product name')
""",
    )

    violations = check_files([path])

    assert violations
    assert 'contract root selector' in violations[0].reason


@pytest.mark.parametrize(
    'source',
    [
        'root = ys.xpath("//article")',
        "root: str = '.product-card'",
        'root = build_root()',
    ],
)
def test_rejects_root_assignment_forms(tmp_path: Path, source: str) -> None:
    path = _write(
        tmp_path,
        f"""
import yosoi as ys

class Product(ys.Contract):
    {source}
""",
    )

    violations = check_files([path])

    assert violations
    assert 'contract root selector' in violations[0].reason


@pytest.mark.parametrize('factory', ['css', 'xpath', 'ys.css', 'ys.xpath'])
def test_rejects_selector_factory_calls(tmp_path: Path, factory: str) -> None:
    path = _write(
        tmp_path,
        f"""
selector = {factory}('.product-card')
""",
    )

    violations = check_files([path])

    assert violations
    assert any('selector factory call' in violation.reason for violation in violations)


def test_rejects_selector_keyword_literal(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
import yosoi as ys

class Product(ys.Contract):
    name: str = ys.Field(description='Product name', selector='h2.title')
""",
    )

    violations = check_files([path])

    assert violations
    assert any('selector' in violation.reason for violation in violations)


@pytest.mark.parametrize('keyword', ['selector', 'selectors', 'root_selector', 'row_selector'])
def test_rejects_selector_keyword_names(tmp_path: Path, keyword: str) -> None:
    path = _write(
        tmp_path,
        f"""
import yosoi as ys

field = ys.Field(description='Product name', {keyword}='.product-card')
""",
    )

    violations = check_files([path])

    assert violations
    assert f'{keyword}=...' in violations[0].reason


def test_rejects_selector_keyword_collection_literal(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
import yosoi as ys

field = ys.Field(description='Product name', selectors=['.product-card'])
""",
    )

    violations = check_files([path])

    assert violations
    assert 'selectors=...' in violations[0].reason


def test_rejects_selector_keyword_composed_literal(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
import yosoi as ys

field = ys.Field(description='Product name', selector=f'.{class_name}')
""",
    )

    violations = check_files([path])

    assert violations
    assert any('selector' in violation.reason for violation in violations)


def test_allows_selector_keyword_without_selector_literal(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
import yosoi as ys

field = ys.Field(description='Product name', selector='discover this field')
""",
    )

    assert check_files([path]) == []


def test_rejects_browser_selector_inside_string(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
EXTRACT_JS = \"document.querySelectorAll('.product-card')\"
""",
    )

    violations = check_files([path])

    assert violations
    assert 'browser selector API' in violations[0].reason


@pytest.mark.parametrize(
    'source',
    [
        "tab.querySelector('.product-card')",
        "tab.querySelectorAll('.product-card')",
        "node.closest('.product-card')",
        "node.matches('.product-card')",
    ],
)
def test_rejects_browser_selector_method_calls(tmp_path: Path, source: str) -> None:
    path = _write(tmp_path, source)

    violations = check_files([path])

    assert violations
    assert 'browser selector API' in violations[0].reason


@pytest.mark.parametrize(
    'source',
    [
        "product_selector = '.product-card'",
        "product_selectors = ['.product-card']",
        "product_xpath = '//article'",
        "product_css = 'div[data-id]'",
        'extract_root = "document.evaluate(\'//article\', document)"',
    ],
)
def test_rejects_selector_like_assignments(tmp_path: Path, source: str) -> None:
    path = _write(tmp_path, source)

    violations = check_files([path])

    assert violations
    assert 'selector-like name' in violations[0].reason or 'browser selector API' in violations[0].reason


def test_rejects_selector_like_attribute_assignment(tmp_path: Path) -> None:
    path = _write(tmp_path, "contract.selector = '.product-card'\n")

    violations = check_files([path])

    assert violations
    assert 'selector-like name' in violations[0].reason


def test_allows_selector_literal_assigned_to_unknown_target(tmp_path: Path) -> None:
    path = _write(tmp_path, "items[0] = '.product-card'\n")

    violations = check_files([path])

    assert violations
    assert 'selector-looking string literal' in violations[0].reason


@pytest.mark.parametrize(
    'source',
    [
        "klass = 'product-card'\nproduct_selector = f'.{klass}'",
        "prefix = '.'\nproduct_selector = prefix + 'product-card'",
        "product_selector = '.' + 'product-card'",
    ],
)
def test_rejects_composed_selector_literals(tmp_path: Path, source: str) -> None:
    path = _write(tmp_path, source)

    violations = check_files([path])

    assert violations
    assert any('selector' in violation.reason for violation in violations)


def test_allows_dotted_domains_and_replay_ids(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
URL = 'https://qscrape.dev/l1/eshop/catalog'
NODE_ID = 'google.navigate'
DOMAIN = 'google.com'
""",
    )

    assert check_files([path]) == []


def test_allows_non_selector_f_string(tmp_path: Path) -> None:
    path = _write(tmp_path, "message = f'hello {name}'\n")

    assert check_files([path]) == []


def test_truncates_long_selector_values(tmp_path: Path) -> None:
    path = _write(tmp_path, f"product_selector = '.{'a' * 120}'\n")

    violations = check_files([path])

    assert violations
    assert len(violations[0].value) == 100
    assert violations[0].value.endswith('...')


def test_ignores_non_python_files(tmp_path: Path) -> None:
    path = tmp_path / 'example.txt'
    path.write_text("root = ys.css('.product-card')")

    assert check_files([path]) == []


def test_checks_python_files_under_directory(tmp_path: Path) -> None:
    nested = tmp_path / 'examples' / 'l1'
    nested.mkdir(parents=True)
    path = nested / 'catalog.py'
    path.write_text("root = ys.css('.product-card')")

    violations = check_files([tmp_path])

    assert violations
    assert {violation.path for violation in violations} == {path}


def test_checks_skip_ignored_directories(tmp_path: Path) -> None:
    ignored = tmp_path / '.venv'
    ignored.mkdir()
    (ignored / 'catalog.py').write_text("root = ys.css('.product-card')")

    assert check_files([tmp_path]) == []


def test_main_defaults_to_examples_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    examples = tmp_path / 'examples'
    examples.mkdir()
    (examples / 'catalog.py').write_text("title = 'Product name'")
    monkeypatch.chdir(tmp_path)

    assert main() == 0


def test_reports_syntax_errors(tmp_path: Path) -> None:
    path = _write(tmp_path, 'def broken(:\n')

    violations = check_files([path])

    assert violations
    assert violations[0].reason == 'syntax error'


def test_main_returns_zero_when_examples_are_clean(tmp_path: Path) -> None:
    path = _write(tmp_path, 'title = "Product name"\n')

    assert main([str(path)]) == 0


def test_main_prints_violations(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, "root = ys.css('.product-card')\n")

    exit_code = main([str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert 'Hard-coded selectors are not allowed in examples' in captured.out
    assert str(path) in captured.out

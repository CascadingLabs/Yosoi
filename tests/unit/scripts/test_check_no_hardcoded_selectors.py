from pathlib import Path

from scripts.check_no_hardcoded_selectors import check_files


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
    assert 'selector=...' in violations[0].reason


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

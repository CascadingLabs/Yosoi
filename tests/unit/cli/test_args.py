"""Tests for yosoi.cli.args — SchemaParamType and _resolve_output_formats."""

import pytest
import rich_click as click

from yosoi.cli.args import SchemaParamType
from yosoi.cli.main import _resolve_output_formats
from yosoi.models.contract import Contract
from yosoi.models.defaults import BUILTIN_SCHEMAS

# ---------------------------------------------------------------------------
# _resolve_output_formats
# ---------------------------------------------------------------------------


class TestResolveOutputFormats:
    def test_single_format(self):
        """Single format returns that format."""
        assert _resolve_output_formats(('json',)) == ['json']

    def test_multiple_formats(self):
        """Multiple formats via tuple."""
        assert set(_resolve_output_formats(('json', 'csv'))) == {'json', 'csv'}

    def test_comma_separated(self):
        """Comma-separated formats are split."""
        result = _resolve_output_formats(('json,csv',))
        assert 'json' in result
        assert 'csv' in result

    def test_md_normalized_to_markdown(self):
        """'md' is normalized to 'markdown'."""
        result = _resolve_output_formats(('md',))
        assert 'markdown' in result
        assert 'md' not in result

    def test_deduplicated(self):
        """Duplicate formats are removed."""
        result = _resolve_output_formats(('json', 'json'))
        assert result == ['json']

    def test_empty_defaults_to_json(self):
        """Empty input defaults to ['json']."""
        result = _resolve_output_formats(())
        assert result == ['json']

    def test_invalid_format_raises(self):
        """Invalid format raises BadParameter."""
        with pytest.raises(click.BadParameter, match='Unknown format'):
            _resolve_output_formats(('invalid',))

    def test_case_insensitive(self):
        """Formats are case-insensitive."""
        result = _resolve_output_formats(('JSON',))
        assert 'json' in result


# ---------------------------------------------------------------------------
# SchemaParamType
# ---------------------------------------------------------------------------


class TestSchemaParamType:
    def test_exact_builtin_match(self):
        """Exact builtin name resolves correctly."""
        param_type = SchemaParamType()
        for name in BUILTIN_SCHEMAS:
            result = param_type.convert(name, None, None)
            assert issubclass(result, Contract)
            break  # just test one

    def test_case_insensitive_builtin(self):
        """Case-insensitive builtin match works."""
        param_type = SchemaParamType()
        first_name = next(iter(BUILTIN_SCHEMAS))
        result = param_type.convert(first_name.upper(), None, None)
        assert issubclass(result, Contract)

    def test_unknown_schema_fails(self):
        """Unknown schema name raises."""
        param_type = SchemaParamType()
        with pytest.raises(click.exceptions.BadParameter):
            param_type.convert('completely_unknown_xyz_schema_9999', None, None)

    def test_get_metavar(self):
        """get_metavar returns expected format string."""
        param_type = SchemaParamType()
        assert 'NAME' in param_type.get_metavar(click.Option(['-c']), None)

    def test_dynamic_import_with_colon(self, tmp_path):
        """Dynamic import via path:ClassName works."""
        import textwrap

        py_file = tmp_path / 'dyn_schema.py'
        py_file.write_text(
            textwrap.dedent("""\
            from yosoi.models.contract import Contract
            class DynTest(Contract):
                title: str = ''
            """)
        )
        param_type = SchemaParamType()
        result = param_type.convert(f'{py_file}:DynTest', None, None)
        assert issubclass(result, Contract)

"""Click parameter types and option group configuration."""

import difflib

import rich_click as click
from rich_click.utils import OptionGroupDict

from yosoi.cli.utils import console_err, load_schema, scan_for_contracts
from yosoi.models.contract import _CONTRACT_REGISTRY, Contract
from yosoi.models.defaults import BUILTIN_SCHEMAS

# ── rich-click styling ──────────────────────────────────────────────
click.rich_click.TEXT_MARKUP = 'rich'
_option_groups: list[OptionGroupDict] = [
    {
        'name': 'Input',
        'options': ['--url', '--file', '--contract', '--limit'],
    },
    {
        'name': 'Model & Fetcher',
        'options': ['--model', '--fetcher'],
    },
    {
        'name': 'Output',
        'options': ['--output', '--summary'],
    },
    {
        'name': 'Concurrency',
        'options': ['--workers'],
    },
    {
        'name': 'Advanced',
        'options': ['--force', '--debug', '--skip-verification', '--log-level'],
    },
]
# Register for both the function name ('main') and the entry-point name ('yosoi')
click.rich_click.OPTION_GROUPS = {
    'main': _option_groups,
    'yosoi': _option_groups,
}


class SchemaParamType(click.ParamType):
    """Click parameter type that resolves schema names with fuzzy matching."""

    name = 'schema'

    def get_metavar(self, param: click.Parameter, ctx: click.Context | None = None) -> str:
        """Return metavar for help text."""
        return 'NAME|path:Class'

    def shell_complete(self, ctx: click.Context, param: click.Parameter, incomplete: str) -> list:
        """Provide shell completion for built-in, registered, and file-scanned schema names."""
        all_names = set(BUILTIN_SCHEMAS) | set(_CONTRACT_REGISTRY) | set(scan_for_contracts())
        return [
            click.shell_completion.CompletionItem(name)  # type: ignore[attr-defined]
            for name in sorted(all_names)
            if name.lower().startswith(incomplete.lower())
        ]

    def convert(self, value: str, param: click.Parameter | None, ctx: click.Context | None) -> type[Contract]:
        """Convert a string value to a Contract class.

        Resolution order:
        1. Exact match in BUILTIN_SCHEMAS
        2. Case-insensitive match in BUILTIN_SCHEMAS
        3. Exact / case-insensitive match in _CONTRACT_REGISTRY (custom schemas)
        4. Fuzzy match across all known schemas (builtins + registry)
        5. Dynamic import via ``path:ClassName``
        """
        # 1. Exact match in builtins
        if value in BUILTIN_SCHEMAS:
            return BUILTIN_SCHEMAS[value]

        # 2. Case-insensitive match in builtins
        lower_builtin = {k.lower(): k for k in BUILTIN_SCHEMAS}
        if value.lower() in lower_builtin:
            return BUILTIN_SCHEMAS[lower_builtin[value.lower()]]

        # 3. Exact / case-insensitive match in registry (custom schemas)
        if value in _CONTRACT_REGISTRY:
            return _CONTRACT_REGISTRY[value]
        lower_registry = {k.lower(): k for k in _CONTRACT_REGISTRY}
        if value.lower() in lower_registry:
            return _CONTRACT_REGISTRY[lower_registry[value.lower()]]

        # 4. Fuzzy match across all known schemas
        all_names = list(set(BUILTIN_SCHEMAS) | set(_CONTRACT_REGISTRY))
        close = difflib.get_close_matches(value, all_names, n=1, cutoff=0.6)
        if close:
            matched = close[0]
            source = BUILTIN_SCHEMAS if matched in BUILTIN_SCHEMAS else _CONTRACT_REGISTRY
            console_err.print(f'[yellow]Warning: fuzzy-matched schema {value!r} → {matched!r}[/yellow]')
            return source[matched]

        # 4b. Scan .py files in CWD for Contract subclasses
        file_contracts = scan_for_contracts()
        if value in file_contracts:
            console_err.print(f'[cyan]ℹ Found {value!r} via file scan → {file_contracts[value]}[/cyan]')
            return load_schema(file_contracts[value])
        close_file = difflib.get_close_matches(value, list(file_contracts), n=1, cutoff=0.6)
        if close_file:
            matched = close_file[0]
            console_err.print(
                f'[yellow]Warning: fuzzy-matched schema {value!r} → {matched!r} (from {file_contracts[matched]})[/yellow]'
            )
            return load_schema(file_contracts[matched])

        # 5. Dynamic import (path:ClassName)
        if ':' in value:
            return load_schema(value)

        available_str = ', '.join(sorted(set(BUILTIN_SCHEMAS) | set(_CONTRACT_REGISTRY) | set(file_contracts)))
        self.fail(f'Unknown schema {value!r}. Available: {available_str}', param, ctx)
        raise AssertionError('unreachable')  # self.fail always raises

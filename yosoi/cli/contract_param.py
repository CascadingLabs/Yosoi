"""Click parameter type for --contract @name|file.json|inline (CAS-121)."""

from __future__ import annotations

import json
import os
from typing import Any

import rich_click as click

from yosoi.models.contract import Contract


class ContractParamType(click.ParamType):
    """Resolve a contract from @name, file.json, inline JSON, or path:Class.

    - ``@name``          — registered or built-in name (strips the leading ``@``)
    - ``path/to/file.json`` — load from JSON file as ContractSpec
    - ``{"name": ...}``  — inline JSON string (ContractSpec)
    - ``path:Class``     — dynamic Python import (existing behavior)
    """

    name = 'contract'

    def get_metavar(self, param: click.Parameter, ctx: click.Context | None = None) -> str:  # noqa: D102
        return '@name|file.json|inline-json|path:Class'

    def convert(  # noqa: D102
        self,
        value: str | Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> type[Contract]:
        if isinstance(value, type) and issubclass(value, Contract):
            return value

        value = str(value).strip()

        # 1. @name — registered contract
        if value.startswith('@'):
            return self._resolve_name(value[1:], param, ctx)

        # 2. Inline JSON — looks like a JSON object
        if value.startswith('{'):
            return self._resolve_inline_json(value, param, ctx)

        # 3. Existing file path ending in .json — load as ContractSpec
        if value.endswith('.json') and os.path.isfile(value):
            return self._resolve_json_file(value, param, ctx)

        # 4. Fallback to the existing SchemaParamType behavior (name / path:Class)
        from yosoi.cli.args import SchemaParamType

        return SchemaParamType().convert(value, param, ctx)

    # ── internals ────────────────────────────────────────────────────────────

    def _resolve_name(self, name: str, param: click.Parameter | None, ctx: click.Context | None) -> type[Contract]:
        from yosoi.cli.args import SchemaParamType

        return SchemaParamType().convert(name, param, ctx)

    def _resolve_inline_json(
        self,
        raw: str,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> type[Contract]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.fail(f'Invalid JSON for --contract: {exc}', param, ctx)
            raise AssertionError('unreachable') from None

        return self._spec_to_contract(data, param, ctx)

    def _resolve_json_file(
        self,
        path: str,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> type[Contract]:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self.fail(f'Cannot read contract file {path!r}: {exc}', param, ctx)
            raise AssertionError('unreachable') from None

        return self._spec_to_contract(data, param, ctx)

    def _spec_to_contract(
        self,
        data: dict[str, Any],
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> type[Contract]:
        try:
            from yosoi.utils.contracts import resolve_contract

            return resolve_contract(data)
        except Exception as exc:  # noqa: BLE001
            self.fail(f'Invalid ContractSpec: {exc}', param, ctx)
            raise AssertionError('unreachable') from None

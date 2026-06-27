"""Machine-readable CLI helpers."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from typing import Any

import rich_click as click

_JSON_FLAGS = {'--json', '-j'}
_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def echo_json(doc: dict[str, Any]) -> None:
    """Emit a stable JSON document to stdout."""
    click.echo(json.dumps(doc, default=str, sort_keys=True))


def _plain(value: str) -> str:
    return _ANSI_RE.sub('', value)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    return str(value)


def _param_doc(param: click.Parameter) -> dict[str, Any]:
    base: dict[str, Any] = {
        'name': param.name,
        'required': param.required,
        'nargs': param.nargs,
        'multiple': param.multiple,
        'type': getattr(param.type, 'name', str(param.type)),
    }
    choices = getattr(param.type, 'choices', None)
    if choices is not None:
        base['choices'] = list(choices)

    if isinstance(param, click.Option):
        base.update(
            {
                'kind': 'option',
                'opts': list(param.opts),
                'secondary_opts': list(param.secondary_opts),
                'help': param.help or '',
                'metavar': param.metavar,
                'default': _jsonable(param.default),
                'is_flag': param.is_flag,
                'flag_value': _jsonable(param.flag_value),
                'hidden': param.hidden,
            }
        )
    elif isinstance(param, click.Argument):
        base.update({'kind': 'argument', 'metavar': param.metavar})
    return base


def command_doc(command: click.Command, ctx: click.Context) -> dict[str, Any]:
    """Serialize a Click command's public surface."""
    options = [_param_doc(param) for param in command.params if isinstance(param, click.Option)]
    arguments = [_param_doc(param) for param in command.params if isinstance(param, click.Argument)]
    doc: dict[str, Any] = {
        'type': 'help',
        'format': 'yosoi.cli.command.v1',
        'command_path': ctx.command_path,
        'name': command.name,
        'help': command.help or '',
        'short_help': command.short_help or command.get_short_help_str(),
        'usage': _plain(command.get_usage(ctx)).strip(),
        'options': options,
        'arguments': arguments,
    }
    if isinstance(command, click.Group):
        commands = []
        for name in command.list_commands(ctx):
            sub = command.get_command(ctx, name)
            if sub is None or sub.hidden:
                continue
            commands.append({'name': name, 'short_help': sub.get_short_help_str(), 'help': sub.help or ''})
        doc['commands'] = commands
    return doc


def _args_want_json(args: Sequence[str]) -> bool:
    return any(arg in _JSON_FLAGS for arg in args)


def _has_json_help(args: Sequence[str], help_names: Sequence[str], command_names: set[str] | None = None) -> bool:
    if not _args_want_json(args):
        return False

    help_name_set = set(help_names)
    for arg in args:
        if command_names is not None and arg in command_names:
            # A subcommand owns any later help flag.
            return False
        if arg in help_name_set:
            return True
    return False


class MachineReadableCommand(click.RichCommand):
    """Click command with JSON help support via ``-h/--help --json``."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        """Emit machine-readable Click errors when ``--json`` is present."""
        raw_args = list(sys.argv[1:] if args is None else args)
        if not _args_want_json(raw_args):
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=standalone_mode,
                windows_expand_args=windows_expand_args,
                **extra,
            )

        try:
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except click.ClickException as exc:
            if not standalone_mode:
                raise
            echo_json(
                {
                    'type': 'error',
                    'format': 'yosoi.cli.error.v1',
                    'error': exc.__class__.__name__,
                    'message': exc.format_message(),
                    'exit_code': exc.exit_code,
                }
            )
            sys.exit(exc.exit_code)

    def get_help_option_names(self, ctx: click.Context) -> list[str]:
        """Return accepted human help flag names."""
        names = list(super().get_help_option_names(ctx))
        for name in ('-h', '--help'):
            if name not in names:
                names.append(name)
        return names

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Emit JSON help before Click consumes human help flags."""
        if _has_json_help(args, self.get_help_option_names(ctx)):
            echo_json(command_doc(self, ctx))
            ctx.exit()
        return super().parse_args(ctx, args)


class MachineReadableGroup(click.RichGroup):
    """Click group that propagates machine-readable command behavior."""

    command_class = MachineReadableCommand

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        """Emit machine-readable Click errors when ``--json`` is present."""
        raw_args = list(sys.argv[1:] if args is None else args)
        if not _args_want_json(raw_args):
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=standalone_mode,
                windows_expand_args=windows_expand_args,
                **extra,
            )

        try:
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except click.ClickException as exc:
            if not standalone_mode:
                raise
            echo_json(
                {
                    'type': 'error',
                    'format': 'yosoi.cli.error.v1',
                    'error': exc.__class__.__name__,
                    'message': exc.format_message(),
                    'exit_code': exc.exit_code,
                }
            )
            sys.exit(exc.exit_code)

    def get_help_option_names(self, ctx: click.Context) -> list[str]:
        """Return accepted human help flag names."""
        names = list(super().get_help_option_names(ctx))
        for name in ('-h', '--help'):
            if name not in names:
                names.append(name)
        return names

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Emit JSON group help while letting subcommands own their flags."""
        if _has_json_help(args, self.get_help_option_names(ctx), set(self.commands)):
            echo_json(command_doc(self, ctx))
            ctx.exit()
        return super().parse_args(ctx, args)


MachineReadableGroup.group_class = MachineReadableGroup

"""Policy-aware annotations for CLI help text."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeAlias

import rich_click as click
from pydantic import BaseModel

from yosoi.models.selectors import SelectorLevel

PolicyPath: TypeAlias = tuple[str, ...]

_BASE_HELP_ATTR = '_yosoi_policy_base_help'


@dataclass(frozen=True)
class PolicyHelpState:
    """Effective policy plus exact paths that were explicitly set by policy layers."""

    policy: Any | None
    explicit_paths: frozenset[PolicyPath]
    error: str | None = None


@dataclass(frozen=True)
class PolicyHelpBinding:
    """One CLI option's policy source paths and selected-value resolver."""

    paths: tuple[PolicyPath, ...]
    resolve: Callable[[Any], object]


def annotate_policy_help(command: click.Command, ctx: click.Context) -> None:
    """Append ``[Policy: ...]`` to options whose values can come from policy."""
    bindings = _bindings_for_command(command)
    if not bindings:
        return
    state = _load_policy_help_state()
    for param in command.params:
        if not isinstance(param, click.Option) or param.name is None:
            continue
        binding = bindings.get(param.name)
        if binding is None:
            continue
        base_help = _base_help(param)
        param.help = _append_policy_note(base_help, _policy_note(state, binding))


def _load_policy_help_state() -> PolicyHelpState:
    from yosoi.policy import Policy
    from yosoi.policy.files import discover_policy_files, load_policy_source

    try:
        env_policy = Policy.from_env()
        file_policies = tuple(load_policy_source(path) for path in discover_policy_files())
        layers = (env_policy, *file_policies)
        return PolicyHelpState(
            policy=Policy.cascade(*layers),
            explicit_paths=frozenset(path for layer in layers for path in _explicit_policy_paths(layer)),
        )
    except Exception as exc:  # noqa: BLE001 - help must remain reachable when policy is broken.
        return PolicyHelpState(policy=None, explicit_paths=frozenset(), error=str(exc))


def _explicit_policy_paths(policy: Any, prefix: PolicyPath = ()) -> Iterable[PolicyPath]:
    for field in policy.model_fields_set:
        path = (*prefix, str(field))
        yield path
        value = getattr(policy, str(field))
        if isinstance(value, BaseModel):
            yield from _explicit_policy_paths(value, path)


def _bindings_for_command(command: click.Command) -> dict[str, PolicyHelpBinding]:
    name = command.name or ''
    if name in {'main', 'scrape', 'discover'}:
        bindings = dict(_SCRAPE_BINDINGS)
        if name == 'scrape':
            bindings.pop('force', None)
            bindings.pop('debug', None)
        elif name == 'discover':
            bindings.pop('force', None)
        return bindings
    if name == 'search':
        return _SEARCH_BINDINGS
    if name == 'crawl':
        return _CRAWL_BINDINGS
    return {}


def _policy_note(state: PolicyHelpState, binding: PolicyHelpBinding) -> str:
    if state.error is not None:
        return f'error: {state.error}'
    if state.policy is None or not any(path in state.explicit_paths for path in binding.paths):
        return 'none'
    return _format_policy_value(binding.resolve(state.policy))


def _append_policy_note(help_text: str, note: str) -> str:
    suffix = f'(policy: {note})'
    return f'{help_text} {suffix}' if help_text else suffix


def _base_help(param: click.Option) -> str:
    existing = getattr(param, _BASE_HELP_ATTR, None)
    if isinstance(existing, str):
        return existing
    base = param.help or ''
    setattr(param, _BASE_HELP_ATTR, base)
    return base


def _format_policy_value(value: object) -> str:
    if value is None:
        return 'none'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, SelectorLevel):
        return value.name.lower()
    if isinstance(value, Enum):
        return value.name.lower()
    if isinstance(value, tuple | list):
        return ','.join(_format_policy_value(item) for item in value) or 'empty'
    return str(value)


def _nested(policy: Any, *path: str) -> object:
    value: object = policy
    for part in path:
        value = getattr(value, part)
        if value is None:
            return None
    return value


def _model_label(policy: Any) -> str | None:
    model = policy.model
    if model is None or model.provider is None or model.model_name is None:
        return None
    return f'{model.provider}:{model.model_name}'


def _scrape_fetcher(policy: Any) -> object:
    scrape = policy.scrape
    return policy.page_runtime(scrape=scrape).fetcher_type


def _crawl_fetcher(policy: Any) -> object:
    crawl = policy.crawl
    if crawl is None:
        return None
    return policy.page_runtime(crawl=crawl).fetcher_type


def _binding(paths: Iterable[PolicyPath], resolver: Callable[[Any], object]) -> PolicyHelpBinding:
    return PolicyHelpBinding(paths=tuple(paths), resolve=resolver)


_SCRAPE_BINDINGS: dict[str, PolicyHelpBinding] = {
    'model': _binding((('model', 'provider'), ('model', 'model_name')), _model_label),
    'force': _binding((('scrape', 'force'),), lambda policy: _nested(policy, 'scrape', 'force')),
    'debug': _binding((('output', 'debug_html'),), lambda policy: _nested(policy, 'output', 'debug_html')),
    'skip_verification': _binding(
        (('scrape', 'skip_verification'),), lambda policy: _nested(policy, 'scrape', 'skip_verification')
    ),
    'output': _binding((('output', 'formats'),), lambda policy: _nested(policy, 'output', 'formats')),
    'flat_files': _binding((('output', 'flat_files'),), lambda policy: _nested(policy, 'output', 'flat_files')),
    'atom_reads': _binding((('atom_reads',),), lambda policy: _nested(policy, 'atom_reads')),
    'fetcher': _binding((('scrape', 'fetcher_type'), ('page', 'fetcher_type')), _scrape_fetcher),
    'workers': _binding((('scrape', 'max_concurrency'),), lambda policy: _nested(policy, 'scrape', 'max_concurrency')),
    'selector_level': _binding(
        (('scrape', 'selector_level'),), lambda policy: _nested(policy, 'scrape', 'selector_level')
    ),
}

_SEARCH_BINDINGS: dict[str, PolicyHelpBinding] = {
    'limit': _binding((('search', 'max_results'),), lambda policy: _nested(policy, 'search', 'max_results')),
    'backend': _binding((('search', 'backend'),), lambda policy: _nested(policy, 'search', 'backend')),
    'region': _binding((('search', 'region'),), lambda policy: _nested(policy, 'search', 'region')),
    'safesearch': _binding((('search', 'safesearch'),), lambda policy: _nested(policy, 'search', 'safesearch')),
    'timelimit': _binding((('search', 'timelimit'),), lambda policy: _nested(policy, 'search', 'timelimit')),
    'page': _binding((('search', 'page'),), lambda policy: _nested(policy, 'search', 'page')),
}

_CRAWL_BINDINGS: dict[str, PolicyHelpBinding] = {
    'fetcher': _binding((('crawl', 'fetcher_type'), ('page', 'fetcher_type')), _crawl_fetcher),
}


__all__ = ['annotate_policy_help']

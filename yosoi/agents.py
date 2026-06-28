"""Install packaged Yosoi agent skills and Pi extensions."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal, cast

AgentTarget = Literal['pi', 'agents', 'claude', 'codex', 'opencode']
AgentScope = Literal['user', 'project']

_SKILLS = ('yosoi-web-workflows', 'yosoi-fetch', 'yosoi-research-frontier')
_TARGETS: tuple[AgentTarget, ...] = ('pi', 'agents', 'claude', 'codex', 'opencode')


@dataclass(frozen=True)
class AgentInstallRecord:
    """One installed, skipped, or dry-run agent asset."""

    target: str
    kind: str
    path: str
    status: Literal['written', 'skipped', 'would-write']


@dataclass(frozen=True)
class AgentInstallResult:
    """Summary of an agent asset install operation."""

    records: list[AgentInstallRecord]

    @property
    def written(self) -> int:
        """Number of files written."""
        return sum(record.status == 'written' for record in self.records)

    @property
    def skipped(self) -> int:
        """Number of existing files skipped."""
        return sum(record.status == 'skipped' for record in self.records)


class AgentInstallError(RuntimeError):
    """Raised when an agent asset cannot be installed safely."""


def install_agent_assets(
    *,
    targets: tuple[AgentTarget, ...],
    scope: AgentScope = 'user',
    force: bool = False,
    dry_run: bool = False,
    home: Path | None = None,
    cwd: Path | None = None,
) -> AgentInstallResult:
    """Install packaged Yosoi skills/extensions into coding-agent config dirs."""
    if scope == 'user':
        root = home or Path.home()
    elif scope == 'project':
        root = cwd or Path.cwd()
    else:
        raise AgentInstallError(f'Unsupported agent install scope: {scope}')

    records: list[AgentInstallRecord] = []
    for target in targets:
        records.extend(_install_target(target, root=root, scope=scope, force=force, dry_run=dry_run))
    return AgentInstallResult(records)


def expand_targets(values: tuple[str, ...]) -> tuple[AgentTarget, ...]:
    """Expand CLI target values, including the `all` sentinel."""
    if not values or 'all' in values:
        return _TARGETS
    targets: list[AgentTarget] = []
    for value in values:
        if value not in _TARGETS:
            raise AgentInstallError(f'Unsupported agent target: {value}')
        targets.append(cast(AgentTarget, value))
    return tuple(dict.fromkeys(targets))


def _install_target(
    target: AgentTarget, *, root: Path, scope: AgentScope, force: bool, dry_run: bool
) -> list[AgentInstallRecord]:
    records: list[AgentInstallRecord] = []
    skills_dir = _skills_dir(target, root, scope)
    for skill_name in _SKILLS:
        source = resources.files('yosoi.agent_assets').joinpath('skills').joinpath(skill_name).joinpath('SKILL.md')
        destination = skills_dir / skill_name / 'SKILL.md'
        records.append(_write_asset(target, 'skill', destination, source.read_text(encoding='utf-8'), force, dry_run))

    if target == 'pi':
        source = resources.files('yosoi.agent_assets').joinpath('pi').joinpath('yosoi-workflows.ts')
        destination = _pi_extension_path(root, scope)
        records.append(
            _write_asset(target, 'extension', destination, source.read_text(encoding='utf-8'), force, dry_run)
        )
    return records


def _skills_dir(target: AgentTarget, root: Path, scope: AgentScope) -> Path:
    if target == 'pi':
        return root / '.pi' / 'agent' / 'skills' if scope == 'user' else root / '.agents' / 'skills'
    if target == 'agents':
        return root / '.agents' / 'skills'
    if target == 'claude':
        return root / '.claude' / 'skills'
    if target == 'codex':
        return root / '.codex' / 'skills'
    if target == 'opencode':
        return root / '.config' / 'opencode' / 'skills'
    raise AgentInstallError(f'Unsupported agent target: {target}')


def _pi_extension_path(root: Path, scope: AgentScope) -> Path:
    if scope == 'user':
        return root / '.pi' / 'agent' / 'extensions' / 'yosoi-workflows.ts'
    return root / '.pi' / 'extensions' / 'yosoi-workflows.ts'


def _write_asset(
    target: str,
    kind: str,
    destination: Path,
    content: str,
    force: bool,
    dry_run: bool,
) -> AgentInstallRecord:
    if destination.exists() and not force:
        return AgentInstallRecord(target=target, kind=kind, path=str(destination), status='skipped')
    if dry_run:
        return AgentInstallRecord(target=target, kind=kind, path=str(destination), status='would-write')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding='utf-8')
    return AgentInstallRecord(target=target, kind=kind, path=str(destination), status='written')

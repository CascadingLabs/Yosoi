"""Local/remote storage helpers for flat Yosoi recipe JSON artifacts."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from yosoi.models.recipe import Recipe
from yosoi.models.snapshot import SnapshotMap
from yosoi.models.spec import ContractSpec
from yosoi.utils.files import atomic_write_text, get_yosoi_storage_path, init_yosoi

GH_PREFIX = 'gh:'
_MAX_RECIPE_BYTES = 5 * 1024 * 1024
_HTTP_TIMEOUT = 30.0


@dataclass(frozen=True)
class RecipeInstallResult:
    """Result of installing a verified recipe into the local cache."""

    recipe: Recipe
    path: Path


def resolve_recipe_ref(source: str) -> str:
    """Resolve ``gh:owner/repo/path@ref`` to a raw GitHub HTTPS URL."""
    if not source.startswith(GH_PREFIX):
        return source
    body = source[len(GH_PREFIX) :]
    if '@' in body:
        path_part, _, ref = body.rpartition('@')
    else:
        path_part, ref = body, 'main'
    parts = [part for part in path_part.split('/') if part]
    if len(parts) < 3 or not ref:
        raise ValueError('Expected gh:owner/repo/path/to/recipe.json[@ref]')
    owner, repo, *rest = parts
    return f'https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{"/".join(rest)}'


def load_recipe(source: str, *, expected_recipe_id: str | None = None) -> Recipe:
    """Load and verify a recipe from local path, HTTPS URL, or ``gh:`` ref."""
    raw = _fetch_text(source)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Failed to parse recipe from {source!r}: invalid JSON: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError(f'Recipe from {source!r} must be a JSON object')
    if not data.get('recipe_id'):
        raise ValueError(f'Recipe from {source!r} is missing required recipe_id')
    try:
        recipe = Recipe.model_validate(data)
    except Exception as exc:
        raise ValueError(f'Failed to parse recipe from {source!r}: {exc}') from exc
    recipe.verify_integrity()
    if expected_recipe_id is not None and recipe.recipe_id != expected_recipe_id:
        raise ValueError(
            f'Recipe from {source!r} has id {recipe.recipe_id!r}, expected {expected_recipe_id!r}; refusing install.'
        )
    return recipe


def install_recipe(
    source: str, *, expected_recipe_id: str | None = None, cache_dir: str | Path | None = None
) -> RecipeInstallResult:
    """Fetch, verify, and cache a recipe under ``.yosoi/recipes/<sha>.json``."""
    recipe = load_recipe(source, expected_recipe_id=expected_recipe_id)
    recipes_dir = Path(cache_dir) if cache_dir is not None else init_yosoi('recipes')
    recipes_dir.mkdir(parents=True, exist_ok=True)
    filename = recipe.recipe_id.removeprefix('sha256:') + '.json'
    path = recipes_dir / filename
    atomic_write_text(path, recipe.canonical_json())
    return RecipeInstallResult(recipe, path)


def cache_path_for(recipe_id: str) -> Path:
    """Return the default local cache path for a recipe id without creating it."""
    return get_yosoi_storage_path('recipes') / f'{recipe_id.removeprefix("sha256:")}.json'


def parse_selectors_file(path: str | Path) -> dict[str, SnapshotMap]:
    """Parse selector JSON as either one SnapshotMap or domain->SnapshotMap."""
    data = _read_json_file(path)
    if not isinstance(data, dict):
        raise ValueError('selectors JSON must be an object')
    if 'snapshots' in data:
        snap_map = SnapshotMap.model_validate(data)
        return {snap_map.domain: snap_map}
    parsed: dict[str, SnapshotMap] = {}
    for domain, value in data.items():
        if not isinstance(value, dict):
            raise ValueError(f'selectors entry {domain!r} must be an object')
        parsed[domain] = SnapshotMap.model_validate(value)
    if not parsed:
        raise ValueError('selectors JSON must contain at least one domain')
    return parsed


def parse_contract_file(path: str | Path) -> ContractSpec:
    """Parse a canonical ContractSpec JSON file."""
    data = _read_json_file(path)
    return ContractSpec.model_validate(data)


def parse_json_file(path: str | Path) -> Any:
    """Parse an arbitrary JSON file for optional recipe sections."""
    return _read_json_file(path)


def publish_recipe_github(
    recipe: Recipe,
    *,
    repo: str,
    path: str,
    branch: str = 'main',
    token: str | None = None,
    message: str | None = None,
) -> str:
    """Publish one flat recipe JSON file through GitHub's Contents API."""
    token = token or os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN')
    if not token:
        raise ValueError('GitHub publish requires GITHUB_TOKEN or GH_TOKEN')
    if '/' not in repo:
        raise ValueError('--repo must be owner/repo')

    owner_repo = repo.strip('/')
    api_url = f'https://api.github.com/repos/{owner_repo}/contents/{quote(path.lstrip("/"))}'
    sha = _github_existing_sha(api_url, branch=branch, token=token)
    payload: dict[str, Any] = {
        'message': message or f'Publish Yosoi recipe {recipe.recipe_id}',
        'content': base64.b64encode(recipe.canonical_json().encode('utf-8')).decode('ascii'),
        'branch': branch,
    }
    if sha:
        payload['sha'] = sha
    response = _request_json(api_url, method='PUT', token=token, payload=payload)
    content = response.get('content') if isinstance(response, dict) else None
    html_url = content.get('html_url') if isinstance(content, dict) else None
    return str(html_url or f'https://github.com/{owner_repo}/blob/{branch}/{path.lstrip("/")}')


def _fetch_text(source: str) -> str:
    resolved = resolve_recipe_ref(source)
    if resolved.startswith('http://'):
        raise ValueError('Refusing plaintext http recipe fetch; use https, gh:, or a local path')
    if resolved.startswith('https://'):
        return _fetch_https_text(resolved)
    path = Path(resolved)
    if not path.is_file():
        raise FileNotFoundError(f'Recipe file not found: {resolved!r}')
    return path.read_text(encoding='utf-8')


def _fetch_https_text(url: str) -> str:
    raw = b''
    for attempt in Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=5),
        retry=retry_if_exception_type(OSError),
        reraise=True,
    ):
        with (
            attempt,
            urlopen(
                Request(url, headers={'Accept': 'application/json, text/plain, */*'}), timeout=_HTTP_TIMEOUT
            ) as resp,
        ):
            length = int(resp.headers.get('content-length') or 0)
            if length > _MAX_RECIPE_BYTES:
                raise ValueError(f'Recipe is too large ({length} bytes > {_MAX_RECIPE_BYTES})')
            raw = resp.read(_MAX_RECIPE_BYTES + 1)
    if len(raw) > _MAX_RECIPE_BYTES:
        raise ValueError(f'Recipe exceeds {_MAX_RECIPE_BYTES} bytes')
    return raw.decode('utf-8')


def _github_existing_sha(api_url: str, *, branch: str, token: str) -> str | None:
    try:
        response = _request_json(f'{api_url}?ref={quote(branch)}', method='GET', token=token, payload=None)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return str(response.get('sha')) if isinstance(response, dict) and response.get('sha') else None


def _request_json(url: str, *, method: str, token: str, payload: dict[str, Any] | None) -> Any:
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {token}',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    raw = ''
    for attempt in Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=5),
        retry=retry_if_exception_type(OSError),
        reraise=True,
    ):
        with attempt, urlopen(request, timeout=_HTTP_TIMEOUT) as resp:
            raw = resp.read().decode('utf-8')
    return json.loads(raw) if raw else {}


def _read_json_file(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except OSError as exc:
        raise FileNotFoundError(f'Cannot read {str(path)!r}: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON in {str(path)!r}: {exc}') from exc

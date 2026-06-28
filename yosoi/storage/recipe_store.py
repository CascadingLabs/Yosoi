"""Local/remote storage helpers for flat Yosoi recipe JSON artifacts."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
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


@dataclass(frozen=True)
class GistPublishResult:
    """Result of publishing a recipe JSON file as a GitHub Gist."""

    raw_url: str
    html_url: str
    filename: str
    public: bool


@dataclass(frozen=True)
class GitHubPrPublishResult:
    """Result of publishing a recipe via a GitHub pull request."""

    html_url: str
    branch: str
    fork_repo: str
    path: str


def resolve_recipe_ref(source: str) -> str:
    """Resolve GitHub shorthand/blob refs to raw HTTPS JSON URLs."""
    if source.startswith(GH_PREFIX):
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

    parsed = urlparse(source)
    if parsed.scheme == 'https' and parsed.netloc.lower() == 'github.com':
        parts = [part for part in parsed.path.split('/') if part]
        if len(parts) >= 5 and parts[2] == 'blob':
            owner, repo, _blob, ref, *rest = parts
            return f'https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{"/".join(rest)}'
    return source


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
    filename = recipe.recipe_id.replace(':', '-') + '.json'
    path = recipes_dir / filename
    atomic_write_text(path, recipe.canonical_json())
    return RecipeInstallResult(recipe, path)


def cache_path_for(recipe_id: str) -> Path:
    """Return the default local cache path for a recipe id without creating it."""
    return get_yosoi_storage_path('recipes') / f'{recipe_id.replace(":", "-")}.json'


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
    """Publish one verified flat recipe JSON file through GitHub's Contents API."""
    recipe.verify_integrity()
    token = _github_token(token)
    if not token:
        raise ValueError('GitHub publish requires GITHUB_TOKEN, GH_TOKEN, or `gh auth login`')
    owner_repo = _normalize_github_repo(repo)
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


def publish_recipe_github_pr(
    recipe: Recipe,
    *,
    repo: str,
    path: str,
    branch: str = 'main',
    token: str | None = None,
    message: str | None = None,
    pr_branch: str | None = None,
) -> GitHubPrPublishResult:
    """Publish one verified flat recipe JSON through a fork branch and pull request."""
    recipe.verify_integrity()
    token = _github_token(token)
    if not token:
        raise ValueError('GitHub PR publish requires GITHUB_TOKEN, GH_TOKEN, or `gh auth login`')
    owner_repo = _normalize_github_repo(repo)
    login = _github_user_login(token)
    fork_repo = _github_ensure_fork(owner_repo, login=login, token=token)
    target_branch = pr_branch or _recipe_pr_branch(recipe)
    base_sha = _github_branch_sha(owner_repo, branch=branch, token=token)
    _github_create_branch(fork_repo, branch=target_branch, sha=base_sha, token=token)
    publish_recipe_github(
        recipe,
        repo=fork_repo,
        path=path,
        branch=target_branch,
        token=token,
        message=message,
    )
    head = f'{login}:{target_branch}'
    try:
        pr = _request_json(
            f'https://api.github.com/repos/{owner_repo}/pulls',
            method='POST',
            token=token,
            payload={
                'title': message or f'Publish Yosoi recipe {recipe.contract.name}',
                'head': head,
                'base': branch,
                'body': f'Adds Yosoi recipe `{recipe.recipe_id}` at `{path}`.',
            },
        )
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        if exc.code != 422:
            raise ValueError(f'GitHub PR publish failed ({exc.code}): {detail or exc.reason}') from exc
        pr = _github_existing_pr(owner_repo, head=head, base=branch, token=token)
        if pr is None:
            raise ValueError(f'GitHub PR publish failed (422): {detail or exc.reason}') from exc
    html_url = str(pr.get('html_url') or f'https://github.com/{owner_repo}/pulls')
    return GitHubPrPublishResult(html_url=html_url, branch=target_branch, fork_repo=fork_repo, path=path)


def publish_recipe_gist(
    recipe: Recipe,
    *,
    filename: str | None = None,
    description: str | None = None,
    public: bool = False,
    token: str | None = None,
) -> GistPublishResult:
    """Publish one flat recipe JSON file as a GitHub Gist.

    Gists are secret/unlisted by default, not access-controlled private. Anyone
    with the returned URL can read the recipe. Pass ``public=True`` intentionally.
    """
    recipe.verify_integrity()
    token = _github_token(token)
    if not token:
        raise ValueError('GitHub Gist publish requires GITHUB_TOKEN, GH_TOKEN, or `gh auth login`')
    name = filename or f'yosoi-recipe-{recipe.recipe_id.split(":")[-1][:12]}.json'
    payload: dict[str, Any] = {
        'description': description or f'Yosoi recipe {recipe.recipe_id}',
        'public': public,
        'files': {name: {'content': recipe.canonical_json()}},
    }
    response = _request_json('https://api.github.com/gists', method='POST', token=token, payload=payload)
    if not isinstance(response, dict):
        raise ValueError('GitHub Gist publish response was not a JSON object')
    files = response.get('files')
    file_info = files.get(name) if isinstance(files, dict) else None
    raw_url = file_info.get('raw_url') if isinstance(file_info, dict) else None
    if not raw_url:
        raise ValueError('GitHub Gist publish response did not include files[filename].raw_url')
    html_url = str(response.get('html_url') or f'https://gist.github.com/{response.get("id", "")}'.rstrip('/'))
    return GistPublishResult(raw_url=str(raw_url), html_url=html_url, filename=name, public=public)


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


def _normalize_github_repo(repo: str) -> str:
    """Accept owner/repo or GitHub repository URLs."""
    value = repo.strip().removesuffix('.git')
    parsed = urlparse(value)
    if parsed.scheme:
        if parsed.netloc.lower() != 'github.com':
            raise ValueError('--repo URL must be on github.com')
        parts = [part for part in parsed.path.split('/') if part]
    else:
        parts = [part for part in value.strip('/').split('/') if part]
    if len(parts) != 2:
        raise ValueError('--repo must be owner/repo or https://github.com/owner/repo')
    return f'{parts[0]}/{parts[1]}'


def _github_token(token: str | None = None) -> str | None:
    """Resolve GitHub auth from explicit arg, env, or local `gh auth login`."""
    if token:
        return token
    if env_token := (os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN')):
        return env_token
    return _cli_auth_token(['gh', 'auth', 'token'])


def _cli_auth_token(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    resolved = result.stdout.strip()
    return resolved or None


def _recipe_pr_branch(recipe: Recipe) -> str:
    safe_name = re.sub(r'[^a-z0-9._-]+', '-', recipe.contract.name.lower()).strip('-') or 'recipe'
    digest = recipe.recipe_id.split(':')[-1][:12]
    return f'yosoi/{safe_name}-{digest}'


def _github_user_login(token: str) -> str:
    response = _request_json('https://api.github.com/user', method='GET', token=token, payload=None)
    login = response.get('login') if isinstance(response, dict) else None
    if not login:
        raise ValueError('GitHub API did not return authenticated user login')
    return str(login)


def _github_ensure_fork(owner_repo: str, *, login: str, token: str) -> str:
    repo_name = owner_repo.split('/', 1)[1]
    fork_repo = f'{login}/{repo_name}'
    try:
        _request_json(f'https://api.github.com/repos/{fork_repo}', method='GET', token=token, payload=None)
        return fork_repo
    except HTTPError as exc:
        if exc.code != 404:
            raise
    _request_json(f'https://api.github.com/repos/{owner_repo}/forks', method='POST', token=token, payload={})
    for attempt in Retrying(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type(HTTPError),
        reraise=True,
    ):
        with attempt:
            _request_json(f'https://api.github.com/repos/{fork_repo}', method='GET', token=token, payload=None)
    return fork_repo


def _github_branch_sha(owner_repo: str, *, branch: str, token: str) -> str:
    response = _request_json(
        f'https://api.github.com/repos/{owner_repo}/git/ref/heads/{quote(branch)}',
        method='GET',
        token=token,
        payload=None,
    )
    obj = response.get('object') if isinstance(response, dict) else None
    sha = obj.get('sha') if isinstance(obj, dict) else None
    if not sha:
        raise ValueError(f'GitHub branch {branch!r} did not return a SHA')
    return str(sha)


def _github_existing_pr(owner_repo: str, *, head: str, base: str, token: str) -> dict[str, Any] | None:
    response = _request_json(
        f'https://api.github.com/repos/{owner_repo}/pulls?state=open&head={quote(head)}&base={quote(base)}',
        method='GET',
        token=token,
        payload=None,
    )
    if isinstance(response, list) and response and isinstance(response[0], dict):
        return response[0]
    return None


def _github_create_branch(owner_repo: str, *, branch: str, sha: str, token: str) -> None:
    try:
        _request_json(
            f'https://api.github.com/repos/{owner_repo}/git/refs',
            method='POST',
            token=token,
            payload={'ref': f'refs/heads/{branch}', 'sha': sha},
        )
    except HTTPError as exc:
        if exc.code != 422:
            raise


def _github_existing_sha(api_url: str, *, branch: str, token: str) -> str | None:
    try:
        response = _request_json(f'{api_url}?ref={quote(branch)}', method='GET', token=token, payload=None)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return str(response.get('sha')) if isinstance(response, dict) and response.get('sha') else None


def _request_json(
    url: str,
    *,
    method: str,
    token: str,
    payload: dict[str, Any] | None,
    auth_header: str = 'Authorization',
) -> Any:
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    auth_value = f'Bearer {token}' if auth_header == 'Authorization' else token
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            'Accept': 'application/json, application/vnd.github+json',
            auth_header: auth_value,
            'Content-Type': 'application/json',
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


def _http_error_detail(exc: HTTPError) -> str:
    return _github_error_detail(exc.read().decode('utf-8', errors='replace'))


def _github_error_detail(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if not isinstance(payload, dict):
        return body.strip()
    message = str(payload.get('message') or '').strip()
    errors = payload.get('errors')
    if isinstance(errors, list):
        details = []
        for error in errors:
            if isinstance(error, dict):
                parts = [str(error.get(key)) for key in ('resource', 'field', 'code', 'message') if error.get(key)]
                if parts:
                    details.append(' '.join(parts))
        if details:
            return f'{message}: {"; ".join(details)}' if message else '; '.join(details)
    return message


def _read_json_file(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except OSError as exc:
        raise FileNotFoundError(f'Cannot read {str(path)!r}: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON in {str(path)!r}: {exc}') from exc

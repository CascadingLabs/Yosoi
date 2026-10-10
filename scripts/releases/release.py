#!/usr/bin/env python3
"""Prepare and validate public Yosoi release notes."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parents[1]
GENERATED_BEGIN = "<!-- release-notes:generated-begin sha256={} -->"
GENERATED_END = "<!-- release-notes:generated-end -->"
HISTORY_BEGIN = "<!-- release-history:generated-begin -->"
HISTORY_END = re.compile(r"^<!-- release-history:generated-end sha256=([0-9a-f]{64}) -->$")
PLACEHOLDER = re.compile(
    r"(?i)\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|\[\[[^\]]+\]\]"
)
VERSION_PATTERN = re.compile(r"^0\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,4})(?:-rc\.([1-9][0-9]*))?$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HISTORY_INTRO = (
    "This section records the user-visible changes, compatibility impact, and upgrade actions "
    "for each published Yosoi release."
)
METADATA_FIELDS = {
    "title",
    "description",
    "order",
    "draft",
    "version",
    "date",
    "channel",
    "previous",
}


class ReleaseError(Exception):
    """An expected input, contract, or filesystem error."""


@dataclass(frozen=True)
class ReleaseVersion:
    text: str
    minor: int
    patch: int
    candidate: int | None = None

    @property
    def ordering(self) -> tuple[int, int, int, bool, int]:
        return (0, self.minor, self.patch, self.candidate is None, self.candidate or 0)

    @property
    def filename(self) -> str:
        return self.text.replace(".", "-") + ".md"

    @property
    def sidecar_filename(self) -> str:
        return "_" + self.text.replace(".", "-") + ".json"


@dataclass(frozen=True)
class ReleaseDocument:
    path: Path
    metadata: dict[str, Any]
    body: str


def parse_version(text: str) -> ReleaseVersion:
    match = VERSION_PATTERN.fullmatch(text)
    if match is None:
        raise ReleaseError(
            f"invalid beta version {text!r}; expected 0.MINOR.PATCH without leading zeros"
        )
    minor = int(match.group(1))
    patch = int(match.group(2))
    if not 1 <= minor <= 100_000:
        raise ReleaseError("beta MINOR must be between 1 and 100000")
    if not 0 <= patch <= 10_000:
        raise ReleaseError("beta PATCH must be between 0 and 10000")
    candidate = int(match.group(3)) if match.group(3) else None
    return ReleaseVersion(text=text, minor=minor, patch=patch, candidate=candidate)


def parse_date(text: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise ReleaseError(f"invalid release date {text!r}; expected YYYY-MM-DD")
    try:
        value = dt.date.fromisoformat(text)
    except ValueError as error:
        raise ReleaseError(f"invalid calendar date {text!r}") from error
    if value.isoformat() != text:
        raise ReleaseError(f"invalid release date {text!r}; expected YYYY-MM-DD")
    return text


def validate_channel(channel: str, version: ReleaseVersion | None = None) -> str:
    if channel not in {"preview", "recommended"}:
        raise ReleaseError("channel must be 'preview' or 'recommended'")
    if version is not None and version.candidate is not None and channel != "preview":
        raise ReleaseError("release candidates must use the preview channel")
    return channel


def release_paths(root: Path, version: ReleaseVersion) -> tuple[Path, Path]:
    directory = release_directory(root, create=True)
    return directory / version.filename, directory / version.sidecar_filename


def release_directory(root: Path, create: bool = False) -> Path:
    directory = root
    for component in ("docs", "public", "releases"):
        directory = directory / component
        if not os.path.lexists(directory) and create:
            try:
                directory.mkdir()
            except FileExistsError:
                pass
            except OSError as error:
                raise ReleaseError(f"cannot create release directory {directory}: {error}") from error
        if os.path.lexists(directory):
            if directory.is_symlink():
                raise ReleaseError(f"release path cannot contain a symlink: {directory}")
            if not directory.is_dir():
                raise ReleaseError(f"release path component is not a directory: {directory}")
    return directory


def reject_symlink_file(path: Path, description: str) -> None:
    if path.is_symlink():
        raise ReleaseError(f"{description} cannot be a symlink: {path}")


def _line_value(line: str, line_number: int) -> tuple[str, str]:
    match = re.fullmatch(r"([a-z][a-z0-9_-]*):(?:[ \t]+(.*))?", line)
    if match is None:
        raise ReleaseError(f"frontmatter line {line_number} is malformed")
    key = match.group(1)
    raw = match.group(2) or ""
    if "\t" in raw:
        raise ReleaseError(f"frontmatter line {line_number} contains a tab")
    return key, raw


def _strip_yaml_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"' and character == "\\" and not escaped:
            escaped = True
            index += 1
            continue
        if quote == '"' and character == '"' and not escaped:
            quote = None
        elif quote == "'" and character == "'":
            if index + 1 < len(value) and value[index + 1] == "'":
                index += 1
            else:
                quote = None
        elif quote is None and character in {'"', "'"}:
            quote = character
        elif quote is None and character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        escaped = character == "\\" and not escaped
        index += 1
    return value.rstrip()


def _parse_yaml_string(raw: str, key: str, line_number: int) -> str:
    value = _strip_yaml_comment(raw).strip()
    if not value:
        raise ReleaseError(f"frontmatter {key} on line {line_number} must not be empty")
    try:
        if value.startswith('"'):
            parsed = json.loads(value)
        elif value.startswith("'"):
            if not re.fullmatch(r"'(?:[^']|'')*'", value):
                raise ValueError("unclosed single-quoted scalar")
            parsed = value[1:-1].replace("''", "'")
        else:
            if (
                re.match(r"^[&*!|>@{}\[\]`]|^(?:-|\?|:)\s", value)
                or "\t" in value
            ):
                raise ValueError("unsupported YAML syntax")
            parsed = value
    except (json.JSONDecodeError, ValueError) as error:
        raise ReleaseError(f"frontmatter {key} on line {line_number} is not a valid string") from error
    if not isinstance(parsed, str) or not parsed.strip() or "\n" in parsed or "\r" in parsed:
        raise ReleaseError(f"frontmatter {key} on line {line_number} must be one non-empty line")
    return parsed


def parse_frontmatter(source: str, path: Path) -> ReleaseDocument:
    lines = source.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ReleaseError(f"{path}: YAML frontmatter is required")
    end_index: int | None = None
    metadata: dict[str, Any] = {}
    for index, full_line in enumerate(lines[1:], start=1):
        line = full_line.rstrip("\r\n")
        if line == "---":
            end_index = index
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, raw = _line_value(line, index + 1)
        if key not in METADATA_FIELDS:
            raise ReleaseError(f"{path}:{index + 1}: unsupported frontmatter field {key!r}")
        if key in metadata:
            raise ReleaseError(f"{path}:{index + 1}: duplicate frontmatter field {key!r}")
        if key == "draft":
            scalar = _strip_yaml_comment(raw).strip()
            if scalar not in {"true", "false"}:
                raise ReleaseError(f"{path}:{index + 1}: draft must be true or false")
            metadata[key] = scalar == "true"
        elif key == "order":
            scalar = _strip_yaml_comment(raw).strip()
            if not re.fullmatch(r"0|[1-9][0-9]*", scalar):
                raise ReleaseError(f"{path}:{index + 1}: order must be a non-negative integer")
            order = int(scalar)
            if order > (1 << 53) - 1:
                raise ReleaseError(f"{path}:{index + 1}: order is too large")
            metadata[key] = order
        else:
            metadata[key] = _parse_yaml_string(raw, key, index + 1)
    if end_index is None:
        raise ReleaseError(f"{path}: frontmatter has no closing --- line")
    body = "".join(lines[end_index + 1 :])
    return ReleaseDocument(path=path, metadata=metadata, body=body)


def read_document(path: Path) -> ReleaseDocument:
    reject_symlink_file(path, "release note")
    try:
        with path.open("r", encoding="utf-8", newline="") as source_file:
            source = source_file.read()
    except FileNotFoundError as error:
        raise ReleaseError(f"release note does not exist: {path}") from error
    except (OSError, UnicodeError) as error:
        raise ReleaseError(f"cannot read release note {path}: {error}") from error
    return parse_frontmatter(source, path)


def validate_metadata(
    document: ReleaseDocument,
    expected_version: str | None = None,
) -> tuple[ReleaseVersion, str, str | None]:
    metadata = document.metadata
    required = {"title", "description", "draft", "version", "date", "channel"}
    missing = sorted(required - metadata.keys())
    if missing:
        raise ReleaseError(f"{document.path}: missing frontmatter fields: {', '.join(missing)}")
    version = parse_version(metadata["version"])
    if expected_version is not None and version.text != expected_version:
        raise ReleaseError(
            f"{document.path}: frontmatter version {version.text} does not match {expected_version}"
        )
    if document.path.name != version.filename:
        raise ReleaseError(
            f"{document.path}: filename must be {version.filename} for version {version.text}"
        )
    if not metadata["title"].strip():
        raise ReleaseError(f"{document.path}: title must not be empty")
    if not metadata["description"].strip():
        raise ReleaseError(f"{document.path}: description must not be empty")
    date = parse_date(metadata["date"])
    channel = validate_channel(metadata["channel"], version)
    previous_value = metadata.get("previous")
    previous: str | None = None
    if previous_value is not None:
        previous = parse_version(previous_value).text
        if parse_version(previous).ordering >= version.ordering:
            raise ReleaseError(f"{document.path}: previous version must be lower than {version.text}")
    return version, date, previous


def _extract_generated(body: str) -> tuple[str, str, str]:
    lines = body.splitlines(keepends=True)
    begin_indices = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n").startswith("<!-- release-notes:generated-begin sha256=")
    ]
    end_indices = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == GENERATED_END
    ]
    if len(begin_indices) != 1 or len(end_indices) != 1:
        raise ReleaseError("release note must contain one intact imported-notes provenance block")
    begin_index = begin_indices[0]
    end_index = end_indices[0]
    if begin_index >= end_index:
        raise ReleaseError("release note imported-notes markers are out of order")
    if (
        begin_index < 2
        or lines[begin_index - 2].rstrip("\r\n") != "<!-- prettier-ignore-start -->"
        or lines[begin_index - 1].strip()
        or end_index + 2 >= len(lines)
        or lines[end_index + 1].strip()
        or lines[end_index + 2].rstrip("\r\n") != "<!-- prettier-ignore-end -->"
    ):
        raise ReleaseError("release note imported block must be enclosed by intact formatter-ignore markers")
    marker = lines[begin_index].rstrip("\r\n")
    match = re.fullmatch(r"<!-- release-notes:generated-begin sha256=([0-9a-f]{64}) -->", marker)
    if match is None:
        raise ReleaseError("release note imported-notes digest marker is malformed")
    generated_embedded = "".join(lines[begin_index + 1 : end_index])
    without = "".join(lines[:begin_index]) + "".join(lines[end_index + 1 :])
    return match.group(1), generated_embedded, without


def _sidecar_path(root: Path, version: ReleaseVersion) -> Path:
    return release_directory(root) / version.sidecar_filename


def _read_sidecar(path: Path) -> dict[str, Any]:
    reject_symlink_file(path, "release provenance sidecar")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ReleaseError(f"release provenance sidecar is missing: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseError(f"cannot read release provenance sidecar {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseError(f"release provenance sidecar must be a JSON object: {path}")
    return value


def validate_generated_source(
    root: Path,
    document: ReleaseDocument,
    version: ReleaseVersion,
    previous: str | None,
) -> None:
    sidecar_path = _sidecar_path(root, version)
    sidecar = _read_sidecar(sidecar_path)
    required = {
        "schema",
        "version",
        "previous",
        "github_notes_file",
        "generated_source_sha256",
        "generated_source",
    }
    if required - sidecar.keys():
        missing = ", ".join(sorted(required - sidecar.keys()))
        raise ReleaseError(f"release provenance sidecar is missing fields: {missing}")
    if sidecar.get("schema") != 1:
        raise ReleaseError(f"unsupported release provenance schema in {sidecar_path}")
    expected_metadata = {"version": version.text, "previous": previous}
    if any(sidecar.get(key) != expected for key, expected in expected_metadata.items()):
        raise ReleaseError(f"release provenance metadata does not match {document.path}")
    generated_source = sidecar.get("generated_source")
    digest = sidecar.get("generated_source_sha256")
    if not isinstance(generated_source, str) or not isinstance(digest, str):
        raise ReleaseError(f"release provenance source or digest has the wrong type: {sidecar_path}")
    actual_digest = hashlib.sha256(generated_source.encode("utf-8")).hexdigest()
    if digest != actual_digest:
        raise ReleaseError(f"release provenance source digest is invalid: {sidecar_path}")
    embedded_digest, embedded_source, _ = _extract_generated(document.body)
    expected_embedded = generated_source
    if not expected_embedded.endswith("\n"):
        expected_embedded += "\n"
    if embedded_digest != digest:
        raise ReleaseError("release note imported-notes digest marker does not match its sidecar")
    if embedded_source != expected_embedded:
        raise ReleaseError(
            "release note imported attribution or source references changed; restore the complete imported block"
        )


def _plain_text(markdown: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"!?(\[([^\]]*)\])\([^)]*\)", r"\2", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#>*_~`|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _mask_inline_code(line: str) -> str:
    chars = list(line)
    index = 0
    while index < len(line):
        if line[index] != "`" or (index > 0 and line[index - 1] == "\\"):
            index += 1
            continue
        run_end = index + 1
        while run_end < len(line) and line[run_end] == "`":
            run_end += 1
        run_length = run_end - index
        search = run_end
        close_start: int | None = None
        close_end: int | None = None
        while search < len(line):
            candidate = line.find("`", search)
            if candidate < 0:
                break
            candidate_end = candidate + 1
            while candidate_end < len(line) and line[candidate_end] == "`":
                candidate_end += 1
            if candidate_end - candidate == run_length:
                close_start = candidate
                close_end = candidate_end
                break
            search = candidate_end
        if close_start is None or close_end is None:
            index = run_end
            continue
        for position in range(index, close_end):
            if chars[position] not in "\r\n":
                chars[position] = " "
        index = close_end
    return "".join(chars)


def _mask_markdown_code(markdown: str) -> str:
    masked_lines: list[str] = []
    fence_marker: str | None = None
    fence_length = 0
    for full_line in markdown.splitlines(keepends=True):
        content = full_line.rstrip("\r\n")
        newline = full_line[len(content) :]
        if fence_marker is not None:
            closing = re.match(rf"^ {{0,3}}{re.escape(fence_marker)}{{{fence_length},}}[ \t]*$", content)
            masked_lines.append(" " * len(content) + newline)
            if closing is not None:
                fence_marker = None
                fence_length = 0
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", content)
        if opening is not None:
            fence = opening.group(1)
            fence_marker = fence[0]
            fence_length = len(fence)
            masked_lines.append(" " * len(content) + newline)
            continue
        masked_lines.append(_mask_inline_code(content) + newline)
    return "".join(masked_lines)


def _headings(markdown: str) -> list[tuple[int, str, int]]:
    result: list[tuple[int, str, int]] = []
    for index, line in enumerate(_mask_markdown_code(markdown).splitlines()):
        match = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match is not None:
            result.append((len(match.group(1)), match.group(2).strip().casefold(), index))
    return result


def _section(markdown: str, names: set[str]) -> str | None:
    masked = _mask_markdown_code(markdown)
    lines = masked.splitlines()
    matches = [item for item in _headings(masked) if item[1] in names]
    if len(matches) > 1:
        raise ReleaseError(f"release note has duplicate {sorted(names)[0]} sections")
    if not matches:
        return None
    level, _, start = matches[0]
    end = len(lines)
    for heading_level, _, index in _headings(markdown):
        if index > start and heading_level <= level:
            end = index
            break
    return "\n".join(lines[start + 1 : end]).strip()


def _opening(markdown: str) -> str:
    lines = _mask_markdown_code(markdown).splitlines()
    content: list[str] = []
    seen_text = False
    for line in lines:
        heading = re.match(r"^ {0,3}(#{1,6})\s+", line)
        if heading is not None:
            if seen_text or len(heading.group(1)) >= 2:
                break
            continue
        if not line.strip():
            if seen_text:
                break
            continue
        content.append(line)
        seen_text = True
    return "\n".join(content).strip()


def _require_useful(
    text: str,
    section_name: str,
) -> None:
    plain = _plain_text(text)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", plain)
    if not words:
        raise ReleaseError(f"release note needs prose in {section_name}")


def validate_editorial_body(body: str, path: Path) -> None:
    _, _, prose = _extract_generated(body)
    editorial = re.sub(r"<!--.*?-->", " ", prose, flags=re.DOTALL)
    if PLACEHOLDER.search(_mask_markdown_code(editorial)):
        raise ReleaseError(f"{path}: human TODO/TBD/FIXME placeholders must be resolved")

    summary = _section(editorial, {"summary"})
    if summary is None:
        summary = _opening(editorial)
    _require_useful(summary, "Summary or opening")

    highlights = _section(editorial, {"highlights"})
    if highlights is not None:
        _require_useful(highlights, "Highlights")

    upgrading = _section(editorial, {"upgrading", "upgrade"})
    if upgrading is None:
        raise ReleaseError(f"{path}: an Upgrading section is required")
    _require_useful(upgrading, "Upgrading")


def validate_release(
    root: Path,
    version_text: str,
    require_finalized: bool = True,
) -> tuple[ReleaseDocument, ReleaseVersion, str, str | None]:
    version = parse_version(version_text)
    page_path = release_directory(root) / version.filename
    document = read_document(page_path)
    actual_version, date, previous = validate_metadata(document, version_text)
    if PLACEHOLDER.search(document.metadata["title"]) or PLACEHOLDER.search(
        document.metadata["description"]
    ):
        raise ReleaseError(f"{page_path}: title and description must not contain editorial placeholders")
    if previous is None and _has_prior_finalized_release(root, actual_version):
        raise ReleaseError(f"{page_path}: previous must name the explicit prior published release")
    if require_finalized and document.metadata["draft"] is not False:
        raise ReleaseError(f"{page_path}: draft must be false before check/body can publish this page")
    validate_generated_source(root, document, actual_version, previous)
    if require_finalized:
        validate_editorial_body(document.body, page_path)
    return document, actual_version, date, previous


def _has_prior_finalized_release(root: Path, version: ReleaseVersion) -> bool:
    releases_dir = release_directory(root)
    if not os.path.lexists(releases_dir):
        return False
    for path in releases_dir.glob("*.md"):
        if path.name == "index.md" or path.name == version.filename:
            continue
        document = read_document(path)
        other_version, _, _ = validate_metadata(document)
        if document.metadata["draft"] is False and other_version.ordering < version.ordering:
            return True
    return False


def _resolve_root(value: Path) -> Path:
    try:
        return value.resolve(strict=True)
    except OSError as error:
        raise ReleaseError(f"repository root does not exist: {value}") from error


def _target_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _write_temp(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", dir=path.parent, delete=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
            return Path(stream.name)
    except OSError as error:
        raise ReleaseError(f"cannot stage {path}: {error}") from error


def _atomic_create(path: Path, content: bytes) -> None:
    temporary = _write_temp(path, content)
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise ReleaseError(f"refusing to overwrite existing file: {path}") from error
    except OSError as error:
        raise ReleaseError(f"cannot create {path}: {error}") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_replace(path: Path, content: bytes, expected_current: bytes) -> None:
    temporary = _write_temp(path, content)
    try:
        try:
            current = path.read_bytes()
        except OSError as error:
            raise ReleaseError(f"cannot recheck existing file {path}: {error}") from error
        if current != expected_current:
            raise ReleaseError(f"refusing to replace changed file: {path}")
        os.replace(temporary, path)
    except OSError as error:
        raise ReleaseError(f"cannot replace {path}: {error}") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def prepare_release(args: argparse.Namespace) -> None:
    root = _resolve_root(args.root)
    version = parse_version(args.version)
    date = parse_date(args.date)
    channel = validate_channel(args.channel, version)
    previous: str | None = None
    if args.previous is not None and args.previous.casefold() != "none":
        previous = parse_version(args.previous).text
        if parse_version(previous).ordering >= version.ordering:
            raise ReleaseError(f"previous version must be lower than {version.text}")
    if previous is None and _has_prior_finalized_release(root, version):
        raise ReleaseError("--previous VERSION is required when finalized release notes already exist")

    notes_path = Path(args.github_notes)
    try:
        source_bytes = notes_path.read_bytes()
        generated_source = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ReleaseError(f"cannot read GitHub notes input {notes_path}: {error}") from error
    if not generated_source.strip():
        raise ReleaseError("GitHub notes input must contain the complete generated notes body")
    if "release-notes:generated-begin" in generated_source or GENERATED_END in generated_source:
        raise ReleaseError("GitHub notes input contains reserved provenance markers")
    digest = hashlib.sha256(source_bytes).hexdigest()

    page_path, sidecar_path = release_paths(root, version)
    reject_symlink_file(page_path, "release note")
    reject_symlink_file(sidecar_path, "release provenance sidecar")
    if _target_exists(page_path):
        raise ReleaseError(f"refusing to overwrite existing reviewed prose: {page_path}")
    if _target_exists(sidecar_path):
        raise ReleaseError(f"refusing to overwrite existing release provenance: {sidecar_path}")

    environment = Environment(
        loader=FileSystemLoader(str(SCRIPT_DIR / "templates")),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        auto_reload=False,
    )
    template = environment.get_template("release.md.j2")
    rendered = template.render(
        title=f"Yosoi {version.text} release notes",
        description=f"Release notes for Yosoi {version.text}.",
        version=version.text,
        date=date,
        channel=channel,
        previous=previous,
        generated_source=generated_source,
        generated_sha256=digest,
    )
    sidecar = {
        "schema": 1,
        "version": version.text,
        "previous": previous,
        "github_notes_file": notes_path.name,
        "generated_source_sha256": digest,
        "generated_source": generated_source,
    }
    sidecar_bytes = (json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )

    _atomic_create(page_path, rendered.encode("utf-8"))
    try:
        _atomic_create(sidecar_path, sidecar_bytes)
    except ReleaseError:
        try:
            page_path.unlink()
        except OSError:
            pass
        raise
    print(f"Prepared draft {page_path.relative_to(root).as_posix()}")


def _check_result(root: Path, version_text: str) -> dict[str, Any]:
    document, version, date, previous = validate_release(root, version_text)
    return {
        "version": version.text,
        "date": date,
        "channel": document.metadata["channel"],
        "previous": previous,
        "draft": document.metadata["draft"],
        "file": document.path.relative_to(root).as_posix(),
    }


def check_release(args: argparse.Namespace) -> None:
    root = _resolve_root(args.root)
    result = _check_result(root, args.version)
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(f"Release notes valid: {result['file']} ({result['version']}, {result['date']})")


def emit_body(args: argparse.Namespace) -> None:
    root = _resolve_root(args.root)
    document, _, _, _ = validate_release(root, args.version)
    sys.stdout.write(document.body)


def _markdown_inline(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")


def _history_content(root: Path) -> str:
    releases_dir = release_directory(root)
    if not os.path.lexists(releases_dir):
        return "Release entries will appear here as they are published."
    entries: list[tuple[ReleaseVersion, str, str, str]] = []
    for path in sorted(releases_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        document = read_document(path)
        version, date, _ = validate_metadata(document)
        if document.metadata["draft"] is True:
            continue
        validated, _, _, _ = validate_release(root, version.text)
        del validated
        channel = document.metadata["channel"]
        badge = "Preview" if channel == "preview" else "Recommended"
        description = _markdown_inline(document.metadata["description"])
        entries.append((version, date, badge, description))
    entries.sort(key=lambda item: item[0].ordering, reverse=True)
    if not entries:
        return "Release entries will appear here as they are published."
    lines = ["## Releases", ""]
    for version, date, badge, description in entries:
        lines.append(
            f"- [{version.text}]({version.filename}) · {date} · **{badge}** — {description}"
        )
    return "\n".join(lines)


def _history_wrapped(content: str) -> bytes:
    prefix = (
        "# Release notes\n\n"
        "<!-- prettier-ignore-start -->\n\n"
        f"{HISTORY_INTRO}\n\n"
        f"{HISTORY_BEGIN}\n\n"
        f"{content}\n\n"
    )
    digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    return (
        f"{prefix}<!-- release-history:generated-end sha256={digest} -->\n\n"
        "<!-- prettier-ignore-end -->\n"
    ).encode("utf-8")


def _validate_history_ownership(existing: bytes, path: Path) -> str:
    try:
        text = existing.decode("utf-8")
    except UnicodeError as error:
        raise ReleaseError(f"existing history index is not UTF-8: {path}") from error
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "# Release notes":
        raise ReleaseError(f"refusing to overwrite unowned release history index: {path}")
    begin_indices = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == HISTORY_BEGIN
    ]
    if len(begin_indices) != 1:
        raise ReleaseError(f"refusing to overwrite unowned release history index: {path}")
    end_indices = [
        index
        for index, line in enumerate(lines)
        if HISTORY_END.fullmatch(line.rstrip("\r\n")) is not None
    ]
    if len(end_indices) != 1:
        raise ReleaseError(f"refusing to overwrite edited release history index: {path}")
    end_index = end_indices[0]
    prefix = "".join(lines[:end_index])
    match = HISTORY_END.fullmatch(lines[end_index].rstrip("\r\n"))
    suffix = "".join(lines[end_index + 1 :])
    if suffix != "\n<!-- prettier-ignore-end -->\n":
        raise ReleaseError(f"refusing to overwrite edited release history index: {path}")
    if match is None or hashlib.sha256(prefix.encode("utf-8")).hexdigest() != match.group(1):
        raise ReleaseError(f"refusing to overwrite edited release history index: {path}")
    if begin_indices[0] >= end_index:
        raise ReleaseError(f"refusing to overwrite malformed release history index: {path}")
    return text


def generate_history(args: argparse.Namespace) -> None:
    root = _resolve_root(args.root)
    output = release_directory(root, create=True) / "index.md"
    generated = _history_wrapped(_history_content(root))
    reject_symlink_file(output, "release history index")
    if not _target_exists(output):
        _atomic_create(output, generated)
        print(f"Wrote {output.relative_to(root).as_posix()}")
        return
    try:
        existing = output.read_bytes()
    except OSError as error:
        raise ReleaseError(f"cannot read existing history index {output}: {error}") from error
    if existing == generated:
        print(f"Up to date: {output.relative_to(root).as_posix()}")
        return
    _validate_history_ownership(existing, output)
    _atomic_replace(output, generated, existing)
    print(f"Updated {output.relative_to(root).as_posix()}")


def fetch_notes(args: argparse.Namespace) -> None:
    version = parse_version(args.version)
    if not REPOSITORY_PATTERN.fullmatch(args.repository):
        raise ReleaseError("repository must be OWNER/REPO")
    if not args.previous_tag.strip() or not args.target_ref.strip():
        raise ReleaseError("fetch requires explicit non-empty previous-tag and target-ref values")
    command = shutil.which("gh")
    if command is None:
        raise ReleaseError("GitHub CLI 'gh' is required for fetch; offline commands do not need it")
    request = [
        command,
        "api",
        "--method",
        "POST",
        f"repos/{args.repository}/releases/generate-notes",
        "-f",
        f"tag_name=v{version.text}",
        "-f",
        f"target_commitish={args.target_ref}",
        "-f",
        f"previous_tag_name={args.previous_tag}",
    ]
    try:
        completed = subprocess.run(request, check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError as error:
        raise ReleaseError(f"could not start GitHub CLI: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"gh exited with status {completed.returncode}"
        raise ReleaseError(f"GitHub notes request failed: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ReleaseError("GitHub CLI returned invalid JSON for generated notes") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("body"), str):
        raise ReleaseError("GitHub CLI response has no generated notes body")
    output = Path(args.output)
    _atomic_create(output, payload["body"].encode("utf-8"))
    print(f"Saved GitHub notes input to {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and validate Yosoi public release notes.")
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository root (defaults to the checkout containing this script)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="create a non-overwriting draft release page")
    prepare.add_argument("version")
    prepare.add_argument("--date", required=True)
    prepare.add_argument("--channel", required=True, choices=("preview", "recommended"))
    prepare.add_argument("--previous", help="explicit previous beta version, or 'none' for the first")
    prepare.add_argument("--github-notes", required=True, help="offline GitHub notes export file")
    prepare.set_defaults(handler=prepare_release)

    check = subparsers.add_parser("check", help="validate a finalized release note and its provenance")
    check.add_argument("version")
    check.add_argument("--json", action="store_true", help="emit validated metadata as JSON")
    check.set_defaults(handler=check_release)

    body = subparsers.add_parser("body", help="emit a validated finalized Markdown body")
    body.add_argument("version")
    body.set_defaults(handler=emit_body)

    history = subparsers.add_parser("history", help="generate the finalized release index")
    history.set_defaults(handler=generate_history)

    fetch = subparsers.add_parser("fetch", help="explicitly request GitHub-generated notes via gh")
    fetch.add_argument("version")
    fetch.add_argument("--repository", required=True, help="GitHub OWNER/REPO")
    fetch.add_argument("--previous-tag", required=True)
    fetch.add_argument("--target-ref", required=True)
    fetch.add_argument("--output", required=True)
    fetch.set_defaults(handler=fetch_notes)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None and len(sys.argv) == 1:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    handler = args.handler
    try:
        handler(args)
    except ReleaseError as error:
        print(f"release notes: error: {error}", file=sys.stderr)
        return 2
    except TemplateError as error:
        print(f"release notes: template error: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as error:
        print(f"release notes: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

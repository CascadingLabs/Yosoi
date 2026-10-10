#!/usr/bin/env python3
"""Build a fail-closed Python/Rust SDK surface inventory from rustdoc artifacts.

Rust API discovery is deliberately delegated to the repository's compiler-backed
reference generator. This module imports its immutable page artifacts instead
of trying to parse Rust source declarations itself.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import hashlib
import importlib
import inspect
import json
import pkgutil
import re
import sys
import types
import typing
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
TOOL_VERSION = "0.1.0"
STATUS_VALUES = {"mapped", "verified", "stale", "missing", "language-specific"}
SHA256_LENGTH = 64
PUBLIC_DUNDER_MEMBERS = {
    "__eq__",
    "__hash__",
    "__len__",
    "__repr__",
    "__str__",
}


class ParityError(ValueError):
    """Raised when an input cannot safely describe the selected SDK snapshot."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParityError(f"cannot read JSON file {path}: {error}") from error


def _safe_artifact_path(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ParityError(f"unsafe rust reference artifact path: {value!r}")
    return Path(*path.parts)


def _inventory_symbol(
    *,
    symbol_key: str,
    item_id: str,
    rust_path: str,
    aliases: list[str],
    kind: str,
    signature: str,
    surface: str,
    parent: str | None = None,
    trait: str | None = None,
) -> dict[str, Any]:
    return {
        "symbolKey": symbol_key,
        "id": item_id,
        "rustPath": rust_path,
        "aliases": sorted(set(aliases)),
        "kind": kind,
        "signature": signature,
        "rustArguments": (
            _rust_function_arguments(signature)
            if kind == "function"
            else _rust_variant_arguments(signature)
            if kind == "variant"
            else []
        ),
        "surface": surface,
        "parentRustPath": parent,
        "trait": trait,
    }


_MATCHING_DELIMITERS = {"(": ")", "[": "]", "{": "}", "<": ">"}


def _rust_function_arguments(signature: str) -> list[dict[str, Any]]:
    """Split the compiler-rendered fn parameter list while respecting nesting."""
    function_at = signature.find("fn ")
    if function_at < 0:
        raise ParityError(f"rustdoc function signature has no fn keyword: {signature}")
    stack: list[str] = []
    opening = None
    index = function_at + len("fn ")
    while index < len(signature):
        char = signature[index]
        if char == ">" and index > 0 and signature[index - 1] == "-":
            index += 1
            continue
        if char in "([{<":
            if char == "(" and not stack:
                opening = index
                break
            stack.append(char)
        elif char in ")]}>":
            if stack and _MATCHING_DELIMITERS.get(stack[-1]) == char:
                stack.pop()
        index += 1
    if opening is None:
        raise ParityError(f"rustdoc function has no parameter list: {signature}")

    pieces: list[str] = []
    current: list[str] = []
    stack = ["("]
    index = opening + 1
    while index < len(signature):
        char = signature[index]
        if char == ">" and index > 0 and signature[index - 1] == "-":
            current.append(char)
            index += 1
            continue
        if char in "([{<":
            stack.append(char)
            current.append(char)
        elif char in ")]}>":
            if stack and _MATCHING_DELIMITERS.get(stack[-1]) == char:
                stack.pop()
                if not stack:
                    if current:
                        pieces.append("".join(current).strip())
                    break
            current.append(char)
        elif char == "," and len(stack) == 1:
            if current:
                pieces.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if stack:
        raise ParityError(f"unbalanced Rust function signature: {signature}")

    result = []
    for piece in pieces:
        if piece == "...":
            result.append({"name": "...", "type": "...", "receiver": False})
            continue
        if ":" not in piece:
            if piece.replace(" ", "") in {
                "self",
                "&self",
                "&mutself",
            } or piece.endswith(" self"):
                result.append({"name": "self", "type": piece, "receiver": True})
                continue
            raise ParityError(
                f"cannot identify Rust function argument in signature: {piece!r}"
            )
        name, type_text = piece.split(":", 1)
        name = name.strip().removeprefix("mut ").strip()
        result.append(
            {
                "name": name,
                "type": type_text.strip(),
                "receiver": name == "self",
            }
        )
    return result


def _split_rust_delimited_list(signature: str, opening: int) -> list[str]:
    first = signature[opening]
    stack = [first]
    pieces: list[str] = []
    current: list[str] = []
    index = opening + 1
    while index < len(signature):
        char = signature[index]
        if char == ">" and index > 0 and signature[index - 1] == "-":
            current.append(char)
            index += 1
            continue
        if char in "([{<":
            stack.append(char)
            current.append(char)
        elif char in ")]}>":
            if stack and _MATCHING_DELIMITERS.get(stack[-1]) == char:
                stack.pop()
                if not stack:
                    if current:
                        pieces.append("".join(current).strip())
                    return pieces
            current.append(char)
        elif char == "," and len(stack) == 1:
            if current:
                pieces.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    raise ParityError(f"unbalanced Rust signature: {signature}")


def _rust_variant_arguments(signature: str) -> list[dict[str, Any]]:
    """Describe compiler-rendered tuple and record enum-variant payloads."""
    candidates = [
        index for index in (signature.find("("), signature.find("{")) if index >= 0
    ]
    if not candidates:
        return []
    opening = min(candidates)
    delimiter = signature[opening]
    pieces = _split_rust_delimited_list(signature, opening)
    result = []
    for index, piece in enumerate(pieces):
        if delimiter == "(":
            result.append({"name": str(index), "type": piece, "receiver": False})
            continue
        if ":" not in piece:
            raise ParityError(f"cannot identify Rust variant field: {piece!r}")
        name, type_text = piece.split(":", 1)
        result.append(
            {"name": name.strip(), "type": type_text.strip(), "receiver": False}
        )
    return result


def load_rust_inventory(reference_dir: Path, locale: str = "en") -> dict[str, Any]:
    """Load and integrity-check the compiler-derived public reference pages."""
    reference_dir = reference_dir.resolve()
    manifest_path = reference_dir / "manifest.json"
    manifest = read_json(manifest_path)
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("kind") != "rust-api-reference"
    ):
        raise ParityError("input is not a supported rust-api-reference artifact")
    revision = manifest.get("source", {}).get("commit")
    if not isinstance(revision, str) or len(revision) != 40:
        raise ParityError("rust reference manifest has no full source commit")
    if any(char not in "0123456789abcdef" for char in revision):
        raise ParityError("rust reference source commit is not hexadecimal")
    if locale not in manifest.get("locales", []):
        raise ParityError(f"rust reference does not contain locale {locale!r}")

    sdk = manifest.get("sdk") or {}
    crate = sdk.get("crate")
    pages = manifest.get("pages")
    if not isinstance(crate, str) or not isinstance(pages, dict):
        raise ParityError("rust reference manifest is missing sdk or pages")

    inventory: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for slug, descriptor in sorted(pages.items()):
        if not isinstance(descriptor, dict):
            raise ParityError(f"invalid page descriptor for {slug!r}")
        relative = _safe_artifact_path(f"{locale}/{descriptor.get('file', '')}")
        page_path = reference_dir / relative
        component = reference_dir
        for part in relative.parts:
            component = component / part
            if component.is_symlink():
                raise ParityError(
                    f"rust reference artifact contains a symlink: {component}"
                )
        try:
            raw_page = page_path.read_bytes()
        except OSError as error:
            raise ParityError(
                f"cannot read rust reference page {page_path}: {error}"
            ) from error
        expected_digest = (descriptor.get("localeHashes") or {}).get(locale)
        if (
            not isinstance(expected_digest, str)
            or digest_bytes(raw_page) != expected_digest
        ):
            raise ParityError(f"rust reference page integrity failed: {locale}/{slug}")
        try:
            page = json.loads(raw_page)
        except json.JSONDecodeError as error:
            raise ParityError(
                f"invalid JSON in rust reference page {page_path}"
            ) from error
        if page.get("schemaVersion") != 1:
            raise ParityError(f"unsupported page schema in {locale}/{slug}")

        # The index page is an overview that repeats every top-level symbol as a
        # navigation member. Those links are not additional Rust API items.
        if page.get("publicPath") == crate and page.get("kind") == "module":
            continue

        aliases = sorted(
            set(descriptor.get("aliases") or []) | set(page.get("aliases") or [])
        )
        parent = _inventory_symbol(
            symbol_key=f"page:{page['id']}",
            item_id=page["id"],
            rust_path=page["publicPath"],
            aliases=aliases,
            kind=page["kind"],
            signature=page["signature"],
            surface="item",
        )
        _insert_unique(inventory, seen_keys, parent)

        for member in page.get("members", []):
            member_trait = member.get("trait")
            signature_digest = digest_bytes(member["signature"].encode("utf-8"))
            member_key = f"member:{member['id']}@signature:{signature_digest}"
            if member_trait:
                member_key += f"@trait:{member_trait}"
            source = member.get("source") or {}
            if source.get("file") and source.get("lineStart") and source.get("lineEnd"):
                source_key = digest_json(
                    {
                        "file": source["file"],
                        "lineStart": source["lineStart"],
                        "lineEnd": source["lineEnd"],
                    }
                )
                member_key += f"@source:{source_key}"
            record = _inventory_symbol(
                symbol_key=member_key,
                item_id=member["id"],
                rust_path=member["publicPath"],
                aliases=[],
                kind=member["kind"],
                signature=member["signature"],
                surface="member",
                parent=page["publicPath"],
                trait=member_trait,
            )
            _insert_unique(inventory, seen_keys, record)

    inventory.sort(key=lambda item: item["symbolKey"])
    signature = digest_json(inventory)
    build = manifest.get("build") or {}
    feature_profile = {
        "requestedFeatures": sorted(build.get("features") or []),
        "defaultFeaturesEnabled": True,
        "target": build.get("target"),
        "referenceGeneratorDigest": build.get("generatorDigest"),
        "compiler": {
            "toolchain": build.get("toolchain"),
            "rustdocVersion": build.get("rustdocVersion"),
            "compilerCommit": build.get("compilerCommit"),
            "rustdocFormatVersion": build.get("formatVersion"),
        },
    }
    feature_digest = digest_json(feature_profile)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rust-public-sdk-inventory",
        "sourceRevision": revision,
        "sdk": {
            "crate": crate,
            "package": sdk.get("package"),
            "version": sdk.get("version"),
        },
        "reference": {
            "version": manifest.get("version"),
            "generatorDigest": build.get("generatorDigest"),
            "locale": locale,
        },
        "featureProfile": feature_profile,
        "featureProfileDigest": feature_digest,
        "inventorySignature": signature,
        "items": inventory,
    }


def _insert_unique(
    inventory: list[dict[str, Any]], seen: set[str], item: dict[str, Any]
) -> None:
    key = item["symbolKey"]
    if key in seen:
        prior = next(existing for existing in inventory if existing["symbolKey"] == key)
        if prior != item:
            raise ParityError(f"conflicting duplicate rustdoc symbol: {key}")
        return
    seen.add(key)
    inventory.append(item)


def _annotation_metadata(value: Any) -> str:
    """Describe validator metadata without process-local object addresses."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return repr(value)
    if inspect.isclass(value):
        return f"{value.__module__}.{value.__qualname__}"
    if inspect.isfunction(value):
        captured = []
        for cell in value.__closure__ or ():
            try:
                captured.append(_annotation_metadata(cell.cell_contents))
            except ValueError:
                captured.append("<empty cell>")
        suffix = f"[{', '.join(captured)}]" if captured else ""
        return f"{value.__module__}.{value.__qualname__}{suffix}"
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(_annotation_metadata(item) for item in value) + "]"
    if dataclasses.is_dataclass(value):
        fields = ", ".join(
            f"{field.name}={_annotation_metadata(getattr(value, field.name))}"
            for field in dataclasses.fields(value)
        )
        return f"{type(value).__module__}.{type(value).__qualname__}({fields})"
    # Unknown metadata stays explicit rather than relying on an unstable repr.
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def _annotation_text(value: Any) -> str | None:
    if value is inspect.Signature.empty:
        return None
    origin = typing.get_origin(value)
    if origin is not None:
        arguments = typing.get_args(value)
        name = getattr(origin, "__qualname__", None) or str(origin)
        if origin is typing.Annotated:
            parts = [_annotation_text(arguments[0]) or "None"]
            parts.extend(_annotation_metadata(item) for item in arguments[1:])
        elif origin is typing.Literal:
            parts = [_annotation_metadata(item) for item in arguments]
        else:
            parts = [_annotation_text(item) or "None" for item in arguments]
        return name + "[" + ", ".join(parts) + "]"
    return getattr(value, "__qualname__", None) or str(value)


class _SignatureAnnotation:
    def __init__(self, value: Any) -> None:
        self.text = _annotation_text(value) or "None"

    def __repr__(self) -> str:
        return self.text


def _safe_default(value: Any) -> Any:
    if value is inspect.Signature.empty:
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [_safe_default(item) for item in value]
    if isinstance(value, list):
        return [_safe_default(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _safe_default(item) for key, item in value.items()}
    value_type = type(value)
    return {
        "display": f"<{value_type.__module__}.{value_type.__qualname__}>",
        "stable": False,
    }


def _describe_signature(
    value: Any, *, bound_member: bool = False
) -> dict[str, Any] | None:
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return None
    parameters_to_describe = list(signature.parameters.values())
    if (
        bound_member
        and parameters_to_describe
        and parameters_to_describe[0].name in {"self", "cls"}
    ):
        parameters_to_describe = parameters_to_describe[1:]
    parameters = []
    for parameter in parameters_to_describe:
        parameters.append(
            {
                "name": parameter.name,
                "kind": parameter.kind.name.lower(),
                "annotation": _annotation_text(parameter.annotation),
                "hasDefault": parameter.default is not inspect.Signature.empty,
                "default": _safe_default(parameter.default),
            }
        )
    return {
        "display": str(
            signature.replace(
                parameters=[
                    parameter.replace(
                        annotation=_SignatureAnnotation(parameter.annotation)
                    )
                    if typing.get_origin(parameter.annotation) is not None
                    else parameter
                    for parameter in parameters_to_describe
                ],
                return_annotation=_SignatureAnnotation(signature.return_annotation)
                if typing.get_origin(signature.return_annotation) is not None
                else signature.return_annotation,
            )
        ),
        "parameters": parameters,
        "returnAnnotation": _annotation_text(signature.return_annotation),
    }


def _is_public_native_exception(
    value: Any, module_name: str, package_name: str
) -> bool:
    """Include extension exceptions re-exported from public Python modules."""
    try:
        return (
            inspect.isclass(value)
            and issubclass(value, BaseException)
            and getattr(value, "__module__", None)
            in {"_native", f"{package_name}._native"}
            and module_name.startswith(f"{package_name}.")
            and not module_name.rsplit(".", 1)[-1].startswith("_")
        )
    except TypeError:
        return False


def _field_default(field: Any) -> dict[str, Any]:
    if field.is_required():
        return {"kind": "required"}
    if field.default_factory is not None:
        factory = field.default_factory
        return {
            "kind": "factory",
            "callable": (
                f"{getattr(factory, '__module__', '')}."
                f"{getattr(factory, '__qualname__', type(factory).__name__)}"
            ),
        }
    return {"kind": "value", "value": _safe_default(field.default)}


def _literal_choices(annotation: Any) -> list[Any]:
    alias_type = getattr(typing, "TypeAliasType", None)
    if alias_type is not None and isinstance(annotation, alias_type):
        try:
            annotation = annotation.__value__
        except Exception:
            return []
    if typing.get_origin(annotation) is typing.Literal:
        return [_safe_default(item) for item in typing.get_args(annotation)]
    origin = typing.get_origin(annotation)
    if origin in {typing.Union, types.UnionType}:
        return [
            value
            for item in typing.get_args(annotation)
            for value in _literal_choices(item)
        ]
    return []


def _annotation_model_types(annotation: Any) -> list[type[Any]]:
    alias_type = getattr(typing, "TypeAliasType", None)
    if alias_type is not None and isinstance(annotation, alias_type):
        try:
            annotation = annotation.__value__
        except Exception:
            return []
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        arguments = typing.get_args(annotation)
        return _annotation_model_types(arguments[0]) if arguments else []
    if origin in {typing.Union, types.UnionType}:
        values = [
            model
            for argument in typing.get_args(annotation)
            for model in _annotation_model_types(argument)
        ]
        return list(dict.fromkeys(values))
    if inspect.isclass(annotation) and isinstance(
        getattr(annotation, "model_fields", None), dict
    ):
        return [annotation]
    return []


def _model_fields(
    value: type[Any], *, _include_nested: bool = True
) -> list[dict[str, Any]]:
    fields = getattr(value, "model_fields", None)
    if not isinstance(fields, dict):
        return []
    result = []
    for name, field in sorted(fields.items()):
        annotation = getattr(field, "annotation", None)
        description = {
            "name": name,
            "alias": getattr(field, "alias", None),
            "validationAlias": str(getattr(field, "validation_alias", None))
            if getattr(field, "validation_alias", None) is not None
            else None,
            "serializationAlias": getattr(field, "serialization_alias", None),
            "annotation": _annotation_text(annotation),
            "literalChoices": _literal_choices(annotation),
            "default": _field_default(field),
        }
        nested_models = _annotation_model_types(annotation) if _include_nested else []
        if len(nested_models) == 1:
            description["modelFields"] = _model_fields(
                nested_models[0], _include_nested=False
            )
        elif nested_models:
            description["modelVariants"] = [
                {
                    "target": f"{model.__module__}.{model.__qualname__}",
                    "fields": _model_fields(model, _include_nested=False),
                }
                for model in nested_models
            ]
        result.append(description)
    return result


def _type_alias_shape(value: Any, package_name: str) -> dict[str, Any]:
    """Describe literal choices and one-level tagged-union members for aliases."""
    alias_type = getattr(typing, "TypeAliasType", None)
    is_pep695_alias = alias_type is not None and isinstance(value, alias_type)
    try:
        annotation = value.__value__ if is_pep695_alias else value
    except Exception:
        annotation = value
    seen_aliases = {id(value)}
    while alias_type is not None and isinstance(annotation, alias_type):
        if id(annotation) in seen_aliases:
            break
        seen_aliases.add(id(annotation))
        try:
            annotation = annotation.__value__
        except Exception:
            break

    metadata: tuple[Any, ...] = ()
    if typing.get_origin(annotation) is typing.Annotated:
        parts = typing.get_args(annotation)
        annotation = parts[0]
        metadata = parts[1:]
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    discriminator = next(
        (
            item.discriminator
            for item in metadata
            if isinstance(getattr(item, "discriminator", None), str)
        ),
        None,
    )

    if origin is typing.Literal:
        alias_kind = "literal"
        choices = _literal_choices(annotation)
    elif origin in {typing.Union, types.UnionType}:
        alias_kind = "discriminated-union" if discriminator else "union"
        choices = []
    else:
        alias_kind = "alias"
        choices = []

    union_members = []
    if origin in {typing.Union, types.UnionType}:
        for member in args:
            member_origin = typing.get_origin(member)
            member_arguments = typing.get_args(member)
            literal_values = (
                [_safe_default(value) for value in member_arguments]
                if member_origin is typing.Literal
                else []
            )
            name = getattr(member, "__qualname__", None) or str(member)
            module = getattr(member, "__module__", None)
            target = (
                f"{module}.{name}"
                if isinstance(module, str) and member_origin is not typing.Literal
                else None
            )
            discriminator_value: Any = None
            discriminator_values: list[Any] = []
            member_fields = _model_fields(member) if inspect.isclass(member) else []
            for description in member_fields:
                model_field = getattr(member, "model_fields", {}).get(
                    description["name"]
                )
                nested = getattr(model_field, "annotation", None)
                if inspect.isclass(nested) and isinstance(
                    getattr(nested, "model_fields", None), dict
                ):
                    description["modelFields"] = _model_fields(nested)
            if discriminator and inspect.isclass(member):
                fields = getattr(member, "model_fields", {})
                field = fields.get(discriminator) if isinstance(fields, dict) else None
                member_annotation = getattr(field, "annotation", None)
                if member_annotation is None:
                    member_annotation = getattr(member, "__annotations__", {}).get(
                        discriminator
                    )
                if typing.get_origin(member_annotation) is typing.Literal:
                    values = typing.get_args(member_annotation)
                    discriminator_values = [_safe_default(value) for value in values]
                    if len(values) == 1:
                        discriminator_value = _safe_default(values[0])
            union_members.append(
                {
                    "name": name,
                    "module": module,
                    "target": target
                    if isinstance(target, str)
                    and target.startswith(f"{package_name}.")
                    and not name.startswith("_")
                    else None,
                    "literalValues": literal_values,
                    "discriminatorValue": discriminator_value,
                    "discriminatorValues": discriminator_values,
                    "fields": member_fields,
                }
            )
    return {
        "kind": alias_kind,
        "annotation": (_annotation_text(annotation) or str(annotation)),
        "choices": choices,
        "discriminator": discriminator,
        "unionMembers": union_members,
    }


def _class_member_descriptions(
    value: type[Any], aliases: list[str]
) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    fields = {item["name"]: item for item in _model_fields(value)}
    declared_members: dict[str, Any] = {}
    annotations: dict[str, Any] = {}
    dataclass_fields: dict[str, dataclasses.Field[Any]] = {}
    package_root = value.__module__.split(".", 1)[0]
    for base in reversed(value.__mro__):
        if base.__module__ == package_root or base.__module__.startswith(
            package_root + "."
        ):
            declared_members.update(vars(base))
            annotations.update(vars(base).get("__annotations__", {}))
            if dataclasses.is_dataclass(base):
                dataclass_fields.update(
                    {
                        field.name: field
                        for field in dataclasses.fields(base)
                        if not field.name.startswith("_")
                    }
                )
    for alias in aliases:
        described_fields: set[str] = set()
        for name, field in fields.items():
            members.append(
                {
                    "target": f"{alias}.{name}",
                    "kind": "field",
                    "annotation": field["annotation"],
                    "field": field,
                }
            )
            described_fields.add(name)
        frozen_dataclass = bool(
            getattr(getattr(value, "__dataclass_params__", None), "frozen", False)
        )
        for name, field in dataclass_fields.items():
            if name in described_fields:
                continue
            annotation = _annotation_text(field.type)
            members.append(
                {
                    "target": f"{alias}.{name}",
                    "kind": "field",
                    "annotation": annotation,
                    "field": {
                        "name": name,
                        "annotation": annotation,
                        "readonly": frozen_dataclass,
                    },
                }
            )
            described_fields.add(name)
        for name, raw_member in declared_members.items():
            if name.startswith("_") and name not in PUBLIC_DUNDER_MEMBERS:
                continue
            target = f"{alias}.{name}"
            if isinstance(raw_member, property):
                members.append(
                    {
                        "target": target,
                        "kind": "property",
                        "signature": _describe_signature(
                            raw_member.fget, bound_member=True
                        )
                        if raw_member.fget
                        else None,
                    }
                )
                continue
            if isinstance(raw_member, types.MemberDescriptorType):
                if name not in described_fields:
                    members.append(
                        {
                            "target": target,
                            "kind": "field",
                            "annotation": _annotation_text(annotations.get(name)),
                            "field": {
                                "name": name,
                                "annotation": _annotation_text(annotations.get(name)),
                                "readonly": False,
                            },
                        }
                    )
                    described_fields.add(name)
                continue
            callable_member = raw_member
            if name.isupper() and isinstance(raw_member, (str, int, float, bool)):
                members.append(
                    {
                        "target": target,
                        "kind": "class-constant",
                        "value": _safe_default(raw_member),
                    }
                )
                continue
            if isinstance(raw_member, (classmethod, staticmethod)):
                callable_member = raw_member.__func__
            if inspect.isfunction(callable_member) or inspect.isbuiltin(
                callable_member
            ):
                members.append(
                    {
                        "target": target,
                        "kind": "callable",
                        "signature": _describe_signature(
                            getattr(value, name), bound_member=True
                        ),
                    }
                )
    return members


def _add_union_properties(targets: dict[str, Any]) -> None:
    """Record properties available on every runtime member of a public union.

    The alias itself is not a class. These targets describe instance access on
    a value annotated with the union, and retain the concrete member witnesses.
    """
    additions = {}
    for alias_target, description in list(targets.items()):
        union = (description.get("alias") or {}).get("unionMembers", [])
        if not union or any(not member.get("target") for member in union):
            continue
        member_targets = [member["target"] for member in union]
        available = []
        for member_target in member_targets:
            prefix = member_target + "."
            available.append(
                {
                    target[len(prefix) :]: target
                    for target, info in targets.items()
                    if target.startswith(prefix)
                    and "." not in target[len(prefix) :]
                    and info.get("kind") in {"field", "property"}
                }
            )
        for name in set.intersection(*(set(member) for member in available)):
            target = alias_target + "." + name
            additions[target] = {
                "target": target,
                "kind": "union-property",
                "members": [member[name] for member in available],
                "signature": {"display": "shared union property", "parameters": []},
            }
    targets.update(additions)


def _python_implementation_digest(package_name: str, package: Any) -> str:
    files: dict[str, str] = {}
    for package_dir in getattr(package, "__path__", []):
        root = Path(package_dir)
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix not in {".py", ".pyi"} and path.name != "py.typed":
                continue
            relative = path.relative_to(root).as_posix()
            files[f"source/{relative}"] = digest_bytes(path.read_bytes())
    native = sys.modules.get(f"{package_name}._native")
    native_path = getattr(native, "__file__", None)
    if isinstance(native_path, str):
        path = Path(native_path)
        if path.is_file() and not path.is_symlink():
            files[f"native/{path.name}"] = digest_bytes(path.read_bytes())
    return digest_json(files)


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def introspect_python_package(
    package_name: str = "yosoi", python_root: Path | None = None
) -> dict[str, Any]:
    """Import public package modules and describe targets and Pydantic fields."""
    python_root_entry: str | None = None
    if python_root is not None:
        python_root_entry = str(python_root.resolve())
        sys.path.insert(0, python_root_entry)
    try:
        package = importlib.import_module(package_name)
        modules = [package]
        package_path = getattr(package, "__path__", None)
        if package_path is not None:
            names = sorted(
                item.name
                for item in pkgutil.walk_packages(
                    package_path, prefix=f"{package_name}."
                )
                if not item.name.rsplit(".", 1)[-1].startswith("_")
            )
            modules.extend(importlib.import_module(name) for name in names)
    except Exception as error:
        raise ParityError(
            f"cannot import {package_name!r} for live Python introspection: {error}"
        ) from error
    finally:
        if python_root_entry is not None and python_root_entry in sys.path:
            sys.path.remove(python_root_entry)

    candidates: dict[int, tuple[Any, set[str], str]] = {}
    for module in modules:
        module_name = module.__name__
        exported = set(getattr(module, "__all__", ()))
        for name, value in vars(module).items():
            if name.startswith("_"):
                continue
            target = f"{module_name}.{name}"
            is_module = isinstance(
                value, types.ModuleType
            ) and value.__name__.startswith(f"{package_name}.")
            is_public_object = (
                inspect.isclass(value)
                or inspect.isfunction(value)
                or inspect.isbuiltin(value)
            ) and (
                getattr(value, "__module__", "")
                in {package_name, f"{package_name}._native"}
                or getattr(value, "__module__", "").startswith(f"{package_name}.")
                or name in exported
                or _is_public_native_exception(value, module_name, package_name)
            )
            pep695_alias = getattr(typing, "TypeAliasType", None)
            is_type_alias = (
                typing.get_origin(value) is not None
                or (pep695_alias is not None and isinstance(value, pep695_alias))
            ) and not isinstance(value, types.ModuleType)
            if not is_module and not is_public_object and not is_type_alias:
                continue
            identity = id(value)
            prior = candidates.get(identity)
            if prior is None:
                candidate_kind = (
                    "module"
                    if is_module
                    else "type-alias"
                    if is_type_alias
                    else "object"
                )
                candidates[identity] = (value, {target}, candidate_kind)
            else:
                prior[1].add(target)

    targets: dict[str, dict[str, Any]] = {}
    objects: list[dict[str, Any]] = []
    for value, target_set, candidate_kind in candidates.values():
        aliases = sorted(target_set, key=lambda target: (target.count("."), target))
        canonical_target = aliases[0]
        if candidate_kind == "module":
            record = {"target": canonical_target, "kind": "module", "aliases": aliases}
            objects.append(record)
            for target in aliases:
                targets[target] = {
                    "kind": "module",
                    "canonicalTarget": canonical_target,
                }
            continue

        if candidate_kind == "type-alias":
            kind = "type-alias"
            alias = _type_alias_shape(value, package_name)
            signature = {
                "display": alias["annotation"],
                "parameters": [],
                "returnAnnotation": None,
            }
            fields = []
            members = []
            enum_values = []
        elif inspect.isclass(value):
            kind = "class"
            signature = _describe_signature(value)
            fields = _model_fields(value)
            members = _class_member_descriptions(value, aliases)
            enum_values = (
                [
                    {"name": member.name, "value": _safe_default(member.value)}
                    for member in value
                ]
                if issubclass(value, enum.Enum)
                else []
            )
        else:
            kind = "callable"
            signature = _describe_signature(value)
            fields = []
            members = []
            enum_values = []
        record = {
            "target": canonical_target,
            "kind": kind,
            "aliases": aliases,
            "signature": signature,
            "fields": fields,
            "enumValues": enum_values,
        }
        if candidate_kind == "type-alias":
            record["alias"] = alias
        objects.append(record)
        for target in aliases:
            targets[target] = {
                "kind": kind,
                "canonicalTarget": canonical_target,
                "signature": signature,
                "fields": fields,
                "enumValues": enum_values,
            }
            if candidate_kind == "type-alias":
                targets[target]["alias"] = alias
        for member in members:
            target = member["target"]
            # A Pydantic field takes precedence over class attributes that merely
            # expose the same model field through BaseModel machinery.
            if target not in targets or member["kind"] == "field":
                targets[target] = member
        for enum_value in enum_values:
            for alias in aliases:
                target = f"{alias}.{enum_value['name']}"
                targets[target] = {
                    "target": target,
                    "kind": "enum-member",
                    "canonicalTarget": canonical_target,
                    "value": enum_value["value"],
                }

    _add_union_properties(targets)
    objects.sort(key=lambda item: item["target"])
    surface_material = {
        "objects": [
            {key: value for key, value in item.items() if key != "aliases"}
            | {"aliases": item["aliases"]}
            for item in objects
        ],
        "targets": targets,
    }
    implementation_digest = _python_implementation_digest(package_name, package)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "python-package-surface",
        "package": package_name,
        "runtime": {
            "implementation": sys.implementation.name,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "abi": getattr(sys, "abiflags", ""),
            "dependencies": {
                "pydantic": _distribution_version("pydantic"),
                "pydantic-core": _distribution_version("pydantic-core"),
            },
        },
        "surfaceDigest": digest_json(surface_material),
        "implementationDigest": implementation_digest,
        "objects": objects,
        "targets": targets,
    }


def load_ledger(path: Path) -> dict[str, Any]:
    ledger = read_json(path)
    if (
        ledger.get("schemaVersion") != SCHEMA_VERSION
        or ledger.get("kind") != "python-rust-sdk-parity-ledger"
    ):
        raise ParityError("unsupported parity ledger schema or kind")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise ParityError("parity ledger must contain an entries array")
    paths = [entry.get("rustPath") for entry in entries]
    if any(not isinstance(item, str) or not item for item in paths):
        raise ParityError("every parity ledger entry needs a rustPath")
    selectors = [
        entry.get("symbolKey") or f"{entry['rustPath']}@trait:{entry.get('trait', '')}"
        for entry in entries
    ]
    if len(selectors) != len(set(selectors)):
        raise ParityError("parity ledger contains duplicate rustPath entries")
    for entry in entries:
        if entry.get("symbolKey") is not None and not isinstance(
            entry["symbolKey"], str
        ):
            raise ParityError(f"invalid symbolKey for ledger entry {entry['rustPath']}")
        if entry.get("trait") is not None and not isinstance(entry["trait"], str):
            raise ParityError(
                f"invalid trait selector for ledger entry {entry['rustPath']}"
            )
        decision = entry.get("decision")
        if decision not in {"mapped", "language-specific"}:
            raise ParityError(f"unsupported ledger decision for {entry['rustPath']}")
        if decision == "mapped" and not isinstance(entry.get("pythonTarget"), str):
            raise ParityError(f"mapped entry has no pythonTarget: {entry['rustPath']}")
        receiver = entry.get("receiverMapping")
        fixed = entry.get("fixedArguments")
        if fixed is not None and (
            not isinstance(fixed, dict)
            or not all(isinstance(key, str) and key for key in fixed)
        ):
            raise ParityError(f"invalid fixed arguments: {entry['rustPath']}")
        if receiver is not None and (
            not isinstance(receiver, dict)
            or not all(
                isinstance(receiver.get(key), str) and receiver[key]
                for key in ("rustArgument", "pythonArgument", "conversion")
            )
        ):
            raise ParityError(f"invalid receiver mapping: {entry['rustPath']}")
        binding = entry.get("variantBinding")
        if binding is not None and (
            not isinstance(binding, dict)
            or not {"discriminator", "tag", "input"}.issubset(binding)
            or set(binding) - {"discriminator", "tag", "input", "derivedFields"}
            or ("derivedFields" in binding and binding["derivedFields"] != ["message"])
            or any(
                not isinstance(binding.get(key), str) or not binding[key]
                for key in ("discriminator", "tag")
            )
            or binding.get("input") != "TypeAdapter.validate_python"
        ):
            raise ParityError(f"invalid variant payload binding: {entry['rustPath']}")
        direction = entry.get("mappingDirection")
        if direction not in {None, "input", "output"}:
            raise ParityError(f"invalid mapping direction: {entry['rustPath']}")
        output_binding = entry.get("outputBinding")
        if direction == "output" and output_binding is None:
            raise ParityError(
                f"output mapping needs outputBinding: {entry['rustPath']}"
            )
        if output_binding is not None:
            required_output = {"kind", "discriminator", "tag", "pythonFields"}
            allowed_output = required_output | {"schemaTarget", "rustType"}
            if (
                not isinstance(output_binding, dict)
                or direction != "output"
                or not required_output.issubset(output_binding)
                or set(output_binding) - allowed_output
                or output_binding.get("kind") not in {"error-details", "outcome-view"}
                or any(
                    not isinstance(output_binding.get(name), str)
                    or not output_binding[name].strip()
                    for name in ("discriminator", "tag")
                )
                or not isinstance(output_binding.get("pythonFields"), list)
            ):
                raise ParityError(f"invalid output binding: {entry['rustPath']}")
            for name in ("schemaTarget", "rustType"):
                if name in output_binding and (
                    not isinstance(output_binding[name], str)
                    or not output_binding[name].strip()
                ):
                    raise ParityError(
                        f"invalid output binding {name}: {entry['rustPath']}"
                    )
            if output_binding["kind"] == "error-details" and not all(
                isinstance(output_binding.get(name), str)
                and output_binding[name].strip()
                for name in ("schemaTarget", "rustType")
            ):
                raise ParityError(
                    "error-details output binding needs schemaTarget and rustType: "
                    f"{entry['rustPath']}"
                )
            if (
                entry.get("fixedArguments")
                or entry.get("receiverMapping")
                or entry.get("argumentMappings")
            ):
                raise ParityError(
                    "output payloads cannot use constructor argument mappings: "
                    f"{entry['rustPath']}"
                )
            if binding is not None or entry.get("argumentMappings"):
                raise ParityError(
                    "output payloads cannot use input variant or argument mappings: "
                    f"{entry['rustPath']}"
                )
            for output_field in output_binding["pythonFields"]:
                if (
                    not isinstance(output_field, dict)
                    or set(output_field)
                    != {"rustArgument", "pythonFieldPath", "conversion"}
                    or any(
                        not isinstance(output_field.get(name), str)
                        or not output_field[name].strip()
                        for name in (
                            "rustArgument",
                            "pythonFieldPath",
                            "conversion",
                        )
                    )
                ):
                    raise ParityError(
                        f"invalid output payload field: {entry['rustPath']}"
                    )
        for field_name in (
            "argumentMappings",
            "defaults",
            "units",
            "cardinality",
        ):
            value = entry.get(field_name, [])
            if not isinstance(value, list):
                raise ParityError(
                    f"{field_name} must be an array for {entry['rustPath']}"
                )
            if not all(isinstance(item, dict) for item in value):
                raise ParityError(
                    f"{field_name} rows must be objects for {entry['rustPath']}"
                )
        for argument in entry.get("argumentMappings", []):
            if not all(
                isinstance(argument.get(field), str) and argument[field]
                for field in ("rustArgument", "pythonArgument", "conversion")
            ):
                raise ParityError(
                    "argument mappings need rustArgument, pythonArgument, and "
                    f"conversion: {entry['rustPath']}"
                )
        for field_name in ("defaults", "units", "cardinality"):
            if any(
                not isinstance(item.get("id"), str) or not item["id"]
                for item in entry.get(field_name, [])
            ):
                raise ParityError(
                    f"{field_name} rows need stable ids for {entry['rustPath']}"
                )
        if decision == "language-specific":
            review = entry.get("review") or {}
            if review.get("status") not in {"proposed", "reviewed"}:
                raise ParityError(
                    "language-specific entry needs review metadata: "
                    f"{entry['rustPath']}"
                )
            if (
                not isinstance(review.get("pythonEquivalent"), str)
                or not review["pythonEquivalent"].strip()
            ):
                raise ParityError(
                    "language-specific entry needs an explicit Python semantic "
                    f"equivalent: {entry['rustPath']}"
                )
        if entry.get("semanticEquivalent") is not None and not isinstance(
            entry["semanticEquivalent"], str
        ):
            raise ParityError(
                f"semanticEquivalent must be a string for {entry['rustPath']}"
            )
    return ledger


def _pin_state(
    ledger: dict[str, Any], rust: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any]:
    source_pin = ledger.get("sourcePin") or {}
    python_pin = ledger.get("pythonPin") or {}
    current = {
        "sourceRevision": rust["sourceRevision"],
        "inventorySignature": rust["inventorySignature"],
        "featureProfileDigest": rust["featureProfileDigest"],
        "pythonSurfaceDigest": python["surfaceDigest"],
        "pythonImplementationDigest": python["implementationDigest"],
    }
    expected = {
        "sourceRevision": source_pin.get("sourceRevision"),
        "inventorySignature": source_pin.get("inventorySignature"),
        "featureProfileDigest": source_pin.get("featureProfileDigest"),
        "pythonSurfaceDigest": python_pin.get("surfaceDigest"),
        "pythonImplementationDigest": python_pin.get("implementationDigest"),
    }
    matches = {
        name: expected[name] is not None and expected[name] == current[name]
        for name in current
    }
    return {
        "current": current,
        "expected": expected,
        "matches": matches,
        "pinned": all(value is not None for value in expected.values()),
        "matchesAll": all(matches.values()),
    }


def _load_evidence(
    path: Path, rust: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any]:
    evidence = read_json(path)
    if (
        evidence.get("schemaVersion") != SCHEMA_VERSION
        or evidence.get("kind") != "yosoi-python-rust-conformance"
    ):
        raise ParityError(f"unsupported conformance evidence file: {path}")
    required_strings = ["runId", "executedAt"]
    if any(
        not isinstance(evidence.get(name), str) or not evidence[name]
        for name in required_strings
    ):
        raise ParityError(f"conformance evidence lacks runId or executedAt: {path}")
    try:
        datetime.fromisoformat(evidence["executedAt"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ParityError(
            f"invalid executedAt in conformance evidence: {path}"
        ) from error
    runner = evidence.get("runner") or {}
    if (
        not isinstance(runner.get("command"), list)
        or not runner["command"]
        or not all(isinstance(part, str) and part for part in runner["command"])
    ):
        raise ParityError(f"conformance evidence needs runner.command: {path}")
    if evidence.get("outcome") not in {"passed", "failed"}:
        raise ParityError(f"invalid conformance run outcome: {path}")
    artifact = evidence.get("resultArtifact") or {}
    artifact_path = artifact.get("path")
    artifact_digest = artifact.get("sha256")
    if not isinstance(artifact_path, str) or not _is_sha256(artifact_digest):
        raise ParityError(
            f"conformance evidence needs a digested resultArtifact: {path}"
        )
    relative = _safe_artifact_path(artifact_path)
    artifact_bytes_path = path.resolve().parent / relative
    try:
        result_bytes = artifact_bytes_path.read_bytes()
    except OSError as error:
        raise ParityError(
            f"cannot read conformance result artifact {artifact_bytes_path}"
        ) from error
    actual_artifact_digest = digest_bytes(result_bytes)
    if actual_artifact_digest != artifact_digest:
        raise ParityError(
            f"conformance result artifact digest mismatch: {artifact_bytes_path}"
        )
    try:
        result_artifact = json.loads(result_bytes)
    except json.JSONDecodeError as error:
        raise ParityError(
            f"conformance result artifact is not JSON: {artifact_bytes_path}"
        ) from error
    if (
        result_artifact.get("schemaVersion") != SCHEMA_VERSION
        or result_artifact.get("kind") != "yosoi-python-rust-conformance-results"
    ):
        raise ParityError(
            f"unsupported conformance result artifact: {artifact_bytes_path}"
        )
    for field_name in ("runId", "outcome", "source", "python", "cases"):
        if canonical_bytes(result_artifact.get(field_name)) != canonical_bytes(
            evidence.get(field_name)
        ):
            raise ParityError(
                f"conformance result artifact disagrees on {field_name}: "
                f"{artifact_bytes_path}"
            )

    source = evidence.get("source") or {}
    python_evidence = evidence.get("python") or {}
    runtime_matches = python_evidence.get("runtime") == python["runtime"]
    snapshot_matches = {
        "sourceRevision": source.get("sourceRevision") == rust["sourceRevision"],
        "inventorySignature": source.get("inventorySignature")
        == rust["inventorySignature"],
        "featureProfileDigest": source.get("featureProfileDigest")
        == rust["featureProfileDigest"],
        "pythonSurfaceDigest": python_evidence.get("surfaceDigest")
        == python["surfaceDigest"],
        "pythonImplementationDigest": python_evidence.get("implementationDigest")
        == python["implementationDigest"],
        "pythonRuntime": runtime_matches,
    }
    cases = evidence.get("cases")
    if not isinstance(cases, list):
        raise ParityError(f"conformance evidence needs a cases array: {path}")
    return {
        "path": str(path),
        "runId": evidence["runId"],
        "outcome": evidence.get("outcome"),
        "snapshotMatches": snapshot_matches,
        "snapshotMatchesAll": all(snapshot_matches.values()),
        "resultArtifactSha256": artifact_digest,
        "cases": cases,
        "runnerCommand": runner["command"],
    }


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(char in "0123456789abcdef" for char in value)
    )


def _case_passes(case: Any, rust_item: dict[str, Any], entry: dict[str, Any]) -> bool:
    if not isinstance(case, dict) or case.get("outcome") != "passed":
        return False
    if not isinstance(case.get("testId"), str) or not case["testId"]:
        return False
    if case.get("symbolKey") is not None:
        if case["symbolKey"] != rust_item["symbolKey"]:
            return False
    elif case.get("rustPath") not in {rust_item["rustPath"], *rust_item["aliases"]}:
        return False
    elif rust_item["trait"] is not None and case.get("trait") != rust_item["trait"]:
        return False
    if case.get("pythonTarget") != entry.get("pythonTarget"):
        return False
    assertions = case.get("comparisons")
    if not isinstance(assertions, list) or not assertions:
        return False
    for assertion in assertions:
        if (
            not isinstance(assertion, dict)
            or not isinstance(assertion.get("name"), str)
            or assertion.get("equal") is not True
            or not _is_sha256(assertion.get("rustSha256"))
            or not _is_sha256(assertion.get("pythonSha256"))
            or assertion["rustSha256"] != assertion["pythonSha256"]
        ):
            return False
    mapping_checks = case.get("mappingChecks")
    if not isinstance(mapping_checks, list):
        return False
    expected_checks = [
        ("argument", item["rustArgument"]) for item in entry.get("argumentMappings", [])
    ]
    if entry.get("receiverMapping"):
        expected_checks.append(("receiver", entry["receiverMapping"]["rustArgument"]))
    expected_checks.extend(("fixed", key) for key in entry.get("fixedArguments", {}))
    expected_checks.extend(
        (kind, item["id"])
        for kind, field in (
            ("default", "defaults"),
            ("unit", "units"),
            ("cardinality", "cardinality"),
        )
        for item in entry.get(field, [])
    )
    for kind, key in expected_checks:
        matching = [
            check
            for check in mapping_checks
            if isinstance(check, dict)
            and check.get("kind") == kind
            and check.get("key") == key
        ]
        if len(matching) != 1:
            return False
        check = matching[0]
        if (
            check.get("equal") is not True
            or not _is_sha256(check.get("rustSha256"))
            or not _is_sha256(check.get("pythonSha256"))
            or check["rustSha256"] != check["pythonSha256"]
        ):
            return False
    return True


def _case_targets_rust_item(case: Any, rust_item: dict[str, Any]) -> bool:
    if not isinstance(case, dict):
        return False
    if case.get("symbolKey") is not None:
        return case["symbolKey"] == rust_item["symbolKey"]
    if case.get("rustPath") not in {rust_item["rustPath"], *rust_item["aliases"]}:
        return False
    return rust_item["trait"] is None or case.get("trait") == rust_item["trait"]


def _case_targets_item(
    case: Any, rust_item: dict[str, Any], entry: dict[str, Any]
) -> bool:
    return _case_targets_rust_item(case, rust_item) and case.get(
        "pythonTarget"
    ) == entry.get("pythonTarget")


def variant_payload_fields(
    member: dict[str, Any], discriminator: str
) -> list[dict[str, Any]]:
    """Describe value fields, including a typed error's details envelope."""
    fields = []
    for field in member.get("fields", []):
        if field["name"] == discriminator:
            continue
        if (
            discriminator == "variant"
            and field["name"] == "details"
            and "modelFields" in field
        ):
            fields.extend(
                {
                    **nested,
                    "name": "details." + nested["name"],
                    "rustName": nested["name"],
                }
                for nested in field["modelFields"]
            )
        else:
            fields.append({**field, "rustName": field["name"]})
    return fields


_PUBLIC_OUTPUT_MEMBER_KINDS = {"field", "property", "union-property"}


def _output_schema_target(
    binding: dict[str, Any],
    python_target: str,
    target: dict[str, Any],
    python_targets: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    schema_target = binding.get("schemaTarget") or python_target
    description = python_targets.get(schema_target)
    if description is None and schema_target == python_target:
        description = target
    return schema_target, description if isinstance(description, dict) else {}


def _public_field(
    schema_target: str, path: str, python_targets: dict[str, Any]
) -> dict[str, Any] | None:
    """Resolve only public fields/properties; never read a value or handle."""
    direct = python_targets.get(f"{schema_target}.{path}")
    if isinstance(direct, dict) and direct.get("kind") in _PUBLIC_OUTPUT_MEMBER_KINDS:
        return direct
    return None


def _path_in_union_member(
    description: dict[str, Any], path: str, tag: str | None
) -> bool:
    alias = description.get("alias") or {}
    segments = path.split(".")
    for member in alias.get("unionMembers", []):
        literal_values = member.get("literalValues", [])
        discriminator_values = member.get("discriminatorValues", [])
        fields = member.get("fields", [])
        field_names = {field.get("name") for field in fields}
        if (
            tag is not None
            and tag not in literal_values
            and tag not in discriminator_values
        ):
            # An external one-key union uses the public key itself as the tag.
            if tag not in field_names:
                continue
        available = field_names
        first = segments[0]
        if first in available:
            if len(segments) == 1:
                return True
            nested = next((field for field in fields if field.get("name") == first), {})
            nested_fields = {
                field.get("name") for field in nested.get("modelFields", [])
            }
            if all(segment in nested_fields for segment in segments[1:]):
                return True
        if len(segments) == 1 and path in literal_values:
            return True
    return False


def _output_field_exists(
    binding: dict[str, Any],
    schema_target: str,
    schema_description: dict[str, Any],
    field_path: str,
    python_targets: dict[str, Any],
) -> bool:
    if field_path == "$":
        return (
            binding.get("kind") == "error-details"
            and schema_target == "yosoi.errors.RustErrorDetails"
            and all(
                _public_field(schema_target, name, python_targets) is not None
                for name in ("rust_type", "variant", "details", "source_chain")
            )
        )
    path = field_path
    prefix = schema_target + "."
    if path.startswith(prefix):
        path = path[len(prefix) :]
    path = path.replace("[*]", ".[*]")
    if not path or any(not segment for segment in path.split(".")):
        return False
    if _model_field_at_path(schema_description.get("fields", []), path) is not None:
        return True
    first, *remaining = path.split(".")
    descriptor = _public_field(schema_target, first, python_targets)
    if descriptor is not None:
        if not remaining:
            return True
        if binding.get("kind") == "error-details" and first == "details":
            # RustErrorDetails.details is a public Mapping[str, Any]. Its keys
            # are variant-specific JSON fields, so their names come from the
            # reviewed binding while this descriptor proves the public mapping.
            annotation = str(descriptor.get("annotation") or "")
            field = descriptor.get("field") or {}
            annotation = annotation or str(field.get("annotation") or "")
            return "Mapping" in annotation and all(
                segment.isidentifier() and not segment.startswith("_")
                for segment in remaining
            )
        if binding.get("kind") == "error-details" and first == "source_chain":
            annotation = str(descriptor.get("annotation") or "")
            field = descriptor.get("field") or {}
            annotation = annotation or str(field.get("annotation") or "")
            return (
                len(remaining) == 1
                and remaining[0] == "[*]"
                and ("tuple" in annotation or "list" in annotation)
            )
        field = descriptor.get("field") or {}
        nested_fields = {item.get("name") for item in field.get("modelFields", [])}
        variants = field.get("modelVariants", [])
        if variants:
            variant_sets = [
                {item.get("name") for item in variant.get("fields", [])}
                for variant in variants
                if isinstance(variant, dict)
            ]
            if variant_sets:
                nested_fields.update(set.intersection(*variant_sets))
        return all(segment in nested_fields for segment in remaining)
    if schema_description.get("kind") == "type-alias":
        return _path_in_union_member(schema_description, path, binding.get("tag"))
    return False


def _output_tag_problem(
    rust_item: dict[str, Any],
    binding: dict[str, Any],
    schema_target: str,
    schema_description: dict[str, Any],
    python_targets: dict[str, Any],
) -> str | None:
    discriminator = binding["discriminator"]
    tag = binding["tag"]
    if binding["kind"] == "error-details":
        if schema_target != "yosoi.errors.RustErrorDetails":
            return "error-details output schema must be yosoi.errors.RustErrorDetails"
        required = {"rust_type", "variant", "details", "source_chain"}
        visible = {
            name
            for name in required
            if _public_field(schema_target, name, python_targets) is not None
        }
        if visible != required:
            return "RustErrorDetails public metadata fields are incomplete"
        rust_type = binding.get("rustType")
        parent_name = rust_item.get("parentRustPath", "").rsplit("::", 1)[-1]
        if discriminator == "variant":
            if tag != rust_item.get("rustPath", "").rsplit("::", 1)[-1]:
                return "RustErrorDetails variant tag does not match the Rust variant"
            if (
                not isinstance(rust_type, str)
                or rust_type.rsplit("::", 1)[-1] != parent_name
            ):
                return (
                    "RustErrorDetails rustType does not identify the Rust parent enum"
                )
        elif discriminator == "rust_type":
            expected_types = {
                argument.get("type", "").rsplit("::", 1)[-1]
                for argument in rust_item.get("rustArguments", [])
            }
            expected_types.add(parent_name)
            if (
                not isinstance(rust_type, str)
                or tag != rust_type
                or rust_type.rsplit("::", 1)[-1] not in expected_types
            ):
                return (
                    "RustErrorDetails rust_type tag is not an expected Rust error type"
                )
        else:
            return "RustErrorDetails discriminator must be variant or rust_type"
        return None

    if discriminator == "external":
        if schema_description.get("kind") != "type-alias":
            return "external output tag requires a live public union alias"
        if not _path_in_union_member(schema_description, tag, tag):
            return "external output tag is absent from the live union literals"
        return None

    alias = schema_description.get("alias") or {}
    if (
        schema_description.get("kind") == "type-alias"
        and alias.get("kind") == "discriminated-union"
    ):
        if alias.get("discriminator") != discriminator:
            return "output discriminator differs from the live union discriminator"
        matches = [
            member
            for member in alias.get("unionMembers", [])
            if tag in member.get("discriminatorValues", [])
        ]
        if len(matches) != 1:
            return "output tag does not select exactly one live union member"
        return None

    if not _output_field_exists(
        binding,
        schema_target,
        schema_description,
        discriminator,
        python_targets,
    ):
        return "output discriminator is absent from the live public schema"
    descriptor = _public_field(schema_target, discriminator, python_targets)
    if descriptor is None:
        descriptor = _model_field_at_path(
            schema_description.get("fields", []), discriminator
        )
    field = (descriptor or {}).get("field") or {}
    choices = (
        field.get("literalChoices") or (descriptor or {}).get("literalChoices") or []
    )
    if choices:
        if tag not in choices:
            return "output tag is absent from live Python literal choices"
        return None
    variant_name = rust_item.get("rustPath", "").rsplit("::", 1)[-1]
    snake_case = re.sub(r"(?<!^)(?=[A-Z])", "_", variant_name).lower()
    if tag != snake_case:
        return "output tag does not match the Rust variant or live literal choices"
    return None


def _output_mapping_configuration_problem(
    rust_item: dict[str, Any],
    entry: dict[str, Any],
    target: dict[str, Any],
    python_targets: dict[str, Any] | None,
) -> str | None:
    binding = entry.get("outputBinding")
    if entry.get("mappingDirection") != "output" or not isinstance(binding, dict):
        return "output mapping requires mappingDirection=output and outputBinding"
    if rust_item.get("kind") != "variant":
        return "outputBinding is supported only for Rust enum variants"
    if entry.get("variantBinding") is not None:
        return "outputBinding cannot also declare an input variantBinding"
    if (
        entry.get("argumentMappings")
        or entry.get("fixedArguments")
        or entry.get("receiverMapping")
    ):
        return "output payloads cannot be declared as constructor arguments"
    if binding.get("kind") not in {"error-details", "outcome-view"}:
        return "unsupported outputBinding kind"
    if (
        not isinstance(binding.get("discriminator"), str)
        or not binding["discriminator"]
    ):
        return "outputBinding needs a public discriminator"
    if not isinstance(binding.get("tag"), str) or not binding["tag"]:
        return "outputBinding needs a literal or status tag"
    python_fields = binding.get("pythonFields")
    if not isinstance(python_fields, list):
        return "outputBinding pythonFields must be an array"
    rust_arguments = rust_item.get("rustArguments")
    if not isinstance(rust_arguments, list):
        return "Rust variant arguments could not be read from the compiler signature"
    expected = {
        argument["name"] for argument in rust_arguments if not argument.get("receiver")
    }
    mapped = [
        field.get("rustArgument") for field in python_fields if isinstance(field, dict)
    ]
    if any(not isinstance(argument, str) or not argument for argument in mapped):
        return "output Python fields must refer to public Rust payload arguments"
    if set(mapped) != expected:
        return "output Python fields must cover the exact Rust payload argument set"
    paths = [field.get("pythonFieldPath") for field in python_fields]
    if any(not isinstance(path, str) or not path for path in paths):
        return "output Python fields need public field paths"
    if len(paths) != len(set(paths)):
        return "output Python field paths must be unique"
    if any(
        not isinstance(field.get("conversion"), str) or not field["conversion"].strip()
        for field in python_fields
    ):
        return "output Python fields need an explicit conversion"

    all_targets = python_targets or {}
    schema_target, schema_description = _output_schema_target(
        binding,
        entry.get("pythonTarget", ""),
        target,
        all_targets,
    )
    if binding.get("schemaTarget") is not None and schema_target not in all_targets:
        return "outputBinding schemaTarget is absent from live Python introspection"
    if not schema_description:
        return "outputBinding has no live public schema description"
    tag_problem = _output_tag_problem(
        rust_item, binding, schema_target, schema_description, all_targets
    )
    if tag_problem is not None:
        return tag_problem
    for field in python_fields:
        if not _output_field_exists(
            binding,
            schema_target,
            schema_description,
            field["pythonFieldPath"],
            all_targets,
        ):
            return (
                "output Python field path is absent from the live public schema: "
                f"{field['pythonFieldPath']}"
            )
    return None


def _field_literal_choices(field: dict[str, Any]) -> list[Any]:
    return list(
        field.get("literalChoices")
        or (field.get("field") or {}).get("literalChoices")
        or []
    )


def _model_field_at_path(
    fields: list[dict[str, Any]], path: str
) -> dict[str, Any] | None:
    current_fields = fields
    current = None
    for segment in path.split("."):
        current = next(
            (field for field in current_fields if field.get("name") == segment),
            None,
        )
        if current is None:
            return None
        current_fields = list(current.get("modelFields", []))
    return current


def _model_public_paths(fields: list[dict[str, Any]], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for field in fields:
        name = field.get("name")
        if not isinstance(name, str) or name.startswith("_"):
            continue
        path = f"{prefix}.{name}" if prefix else name
        paths.add(path)
        nested = field.get("modelFields")
        if isinstance(nested, list):
            paths.update(_model_public_paths(nested, path))
        variants = field.get("modelVariants")
        if isinstance(variants, list) and variants:
            variant_paths = [
                _model_public_paths(variant.get("fields", []), path)
                for variant in variants
                if isinstance(variant, dict)
            ]
            if len(variant_paths) == len(variants):
                paths.update(set.intersection(*variant_paths))
    return paths


def _mapping_configuration_problem(
    rust_item: dict[str, Any],
    entry: dict[str, Any],
    target: dict[str, Any],
    python_targets: dict[str, Any] | None = None,
) -> str | None:
    if (
        entry.get("mappingDirection") == "output"
        or entry.get("outputBinding") is not None
    ):
        return _output_mapping_configuration_problem(
            rust_item, entry, target, python_targets
        )
    if entry.get("mappingDirection") not in {None, "input"}:
        return "unsupported mapping direction"
    if (
        rust_item["kind"] in {"trait", "macro", "proc_macro"}
        and not str(entry.get("semanticEquivalent", "")).strip()
    ):
        return "Rust trait or macro mapping needs an explicit semantic equivalent"
    if rust_item["kind"] not in {"function", "variant"}:
        return None
    rust_arguments = rust_item.get("rustArguments")
    if not isinstance(rust_arguments, list):
        return "Rust function arguments could not be read from the compiler signature"
    expected = {
        argument["name"] for argument in rust_arguments if not argument.get("receiver")
    }
    mappings = entry.get("argumentMappings", [])
    mapped = {argument["rustArgument"] for argument in mappings}
    if expected != mapped:
        details = []
        missing = sorted(expected - mapped)
        extra = sorted(mapped - expected)
        if missing:
            details.append(f"unmapped Rust arguments: {', '.join(missing)}")
        if extra:
            details.append(f"unknown Rust arguments: {', '.join(extra)}")
        return "; ".join(details)
    python_parameters = {
        parameter["name"]
        for parameter in ((target.get("signature") or {}).get("parameters") or [])
        if isinstance(parameter, dict) and isinstance(parameter.get("name"), str)
    }
    binding = entry.get("variantBinding")
    if binding is not None:
        alias = target.get("alias") or {}
        if target.get("kind") == "class" and alias.get("kind") != "discriminated-union":
            discriminator_field = _model_field_at_path(
                target.get("fields", []), binding["discriminator"]
            )
            if discriminator_field is None:
                return "tagged model discriminator is absent from public fields"
            choices = _field_literal_choices(discriminator_field)
            if binding["tag"] not in choices:
                return "tagged model variant tag is absent from live literal choices"
            python_parameters.update(_model_public_paths(target.get("fields", [])))
    receiver = entry.get("receiverMapping")
    if any(key not in python_parameters for key in entry.get("fixedArguments", {})):
        return "fixed argument is absent from the live Python signature"
    for name, value in entry.get("fixedArguments", {}).items():
        field = next(
            (field for field in target.get("fields", []) if field["name"] == name),
            None,
        )
        if (
            field
            and field.get("literalChoices")
            and value not in field["literalChoices"]
        ):
            return "fixed argument value is absent from the live Python literal choices"
    if receiver and (
        not any(
            argument.get("receiver") and argument["name"] == receiver["rustArgument"]
            for argument in rust_arguments
        )
        or receiver["pythonArgument"] not in python_parameters
    ):
        return (
            "explicit receiver mapping does not match Rust self "
            "and a live Python argument"
        )
    if binding is not None:
        plain_tagged_model = (
            target.get("kind") == "class" and alias.get("kind") != "discriminated-union"
        )
        if not plain_tagged_model:
            if (
                rust_item["kind"] != "variant"
                or alias.get("kind") != "discriminated-union"
                or binding.get("discriminator") != alias.get("discriminator")
                or binding.get("input") != "TypeAdapter.validate_python"
            ):
                return (
                    "variant payload binding does not describe a live "
                    "discriminated union"
                )
            members = [
                member
                for member in alias.get("unionMembers", [])
                if binding.get("tag") in member.get("discriminatorValues", [])
            ]
            if len(members) != 1:
                return (
                    "variant discriminator does not select exactly one "
                    "Python payload schema"
                )
            derived = binding.get("derivedFields", [])
            if derived and (
                rust_item.get("rustPath")
                not in {
                    "yosoi::contracts::ExtractionFailure::InvalidContractSchema",
                    "yosoi::contracts::ValidationFailure::InvalidContractSchema",
                }
                or not any(
                    field["name"] == "message" and field.get("annotation") == "str"
                    for field in members[0].get("fields", [])
                )
            ):
                return (
                    "derived variant message is not the reviewed "
                    "Rust schema-error display field"
                )
            python_parameters = {
                field["name"]
                for field in variant_payload_fields(
                    members[0], binding["discriminator"]
                )
                if field["name"] not in derived
            }
            if {
                argument["pythonArgument"] for argument in mappings
            } != python_parameters:
                return (
                    "variant payload mapping does not cover the selected Python fields"
                )
    for argument in mappings:
        if argument["pythonArgument"] not in python_parameters:
            return (
                f"Python argument {argument['pythonArgument']} for Rust argument "
                f"{argument['rustArgument']} is absent from the introspected signature"
            )
    if (
        rust_item["kind"] == "function"
        and target.get("kind") == "class"
        and not str(entry.get("semanticEquivalent", "")).strip()
    ):
        mapped_python = {argument["pythonArgument"] for argument in mappings}
        required_python = {
            parameter["name"]
            for parameter in ((target.get("signature") or {}).get("parameters") or [])
            if isinstance(parameter, dict)
            and parameter.get("hasDefault") is False
            and isinstance(parameter.get("name"), str)
        }
        missing_python = sorted(required_python - mapped_python)
        if missing_python:
            return "unmapped required Python arguments: " + ", ".join(missing_python)
    return None


def build_report(
    rust: dict[str, Any],
    python: dict[str, Any],
    ledger: dict[str, Any],
    evidence_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Join complete Rust and Python inventories with explicit mappings/evidence."""
    evidence_documents = evidence_documents or []
    pin = _pin_state(ledger, rust, python)
    rust_by_path: dict[str, list[dict[str, Any]]] = {}
    rust_by_key = {item["symbolKey"]: item for item in rust["items"]}
    for item in rust["items"]:
        for path in [item["rustPath"], *item["aliases"]]:
            paths = rust_by_path.setdefault(path, [])
            if all(existing["symbolKey"] != item["symbolKey"] for existing in paths):
                paths.append(item)

    entry_by_item: dict[str, dict[str, Any]] = {}
    stale_ledger_entries: list[dict[str, str]] = []
    for entry in ledger["entries"]:
        if entry.get("symbolKey"):
            item = rust_by_key.get(entry["symbolKey"])
            candidates = [item] if item is not None else []
        else:
            candidates = rust_by_path.get(entry["rustPath"], [])
            if "trait" in entry:
                candidates = [
                    item for item in candidates if item["trait"] == entry["trait"]
                ]
        if not candidates:
            stale_ledger_entries.append(
                {
                    "rustPath": entry["rustPath"],
                    "reason": "path absent from current Rust inventory",
                }
            )
            continue
        if len(candidates) > 1:
            raise ParityError(
                f"ambiguous Rust public path {entry['rustPath']}; "
                "ledger must identify symbolKey or trait"
            )
        item = candidates[0]
        if entry["rustPath"] not in {item["rustPath"], *item["aliases"]}:
            stale_ledger_entries.append(
                {
                    "rustPath": entry["rustPath"],
                    "reason": "symbolKey no longer matches rustPath",
                }
            )
            continue
        if item["symbolKey"] in entry_by_item:
            raise ParityError(
                f"multiple ledger rows map the same Rust item: {entry['rustPath']}"
            )
        entry_by_item[item["symbolKey"]] = entry

    evidence_by_item: dict[str, list[dict[str, str]]] = {}
    stale_evidence: dict[str, list[str]] = {}
    for evidence in evidence_documents:
        if evidence.get("outcome") != "passed":
            continue
        for item in rust["items"]:
            entry = entry_by_item.get(item["symbolKey"])
            if not entry or entry.get("decision") != "mapped":
                continue
            rust_cases = [
                case
                for case in evidence["cases"]
                if _case_targets_rust_item(case, item)
            ]
            if not rust_cases:
                continue
            if not evidence["snapshotMatchesAll"]:
                stale_evidence.setdefault(item["symbolKey"], []).append(
                    evidence["runId"]
                )
                continue
            matching = [
                case for case in rust_cases if _case_targets_item(case, item, entry)
            ]
            if not matching:
                stale_evidence.setdefault(item["symbolKey"], []).append(
                    evidence["runId"]
                )
                continue
            passing_cases = [
                case for case in matching if _case_passes(case, item, entry)
            ]
            for case in passing_cases:
                evidence_by_item.setdefault(item["symbolKey"], []).append(
                    {
                        "runId": evidence["runId"],
                        "testId": case["testId"],
                        "resultArtifactSha256": evidence["resultArtifactSha256"],
                        "comparisons": case["comparisons"],
                    }
                )

    report_items = []
    for item in rust["items"]:
        entry = entry_by_item.get(item["symbolKey"])
        status = "missing"
        reason = "no explicit parity ledger mapping"
        target_info = None
        item_evidence: list[dict[str, Any]] = []
        if entry is not None:
            if entry.get("decision") == "language-specific":
                review = entry.get("review") or {}
                if (
                    review.get("status") == "reviewed"
                    and review.get("reviewer")
                    and review.get("rationale")
                    and review.get("pythonEquivalent")
                ):
                    status = "language-specific"
                    reason = review["rationale"]
                else:
                    status = "missing"
                    reason = "language-specific disposition requires completed review"
            else:
                target = entry["pythonTarget"]
                target_info = python["targets"].get(target)
                expected_signature_digest = entry.get("rustSignatureSha256")
                actual_signature_digest = digest_bytes(
                    item["signature"].encode("utf-8")
                )
                signature_stale = (
                    expected_signature_digest is not None
                    and expected_signature_digest != actual_signature_digest
                )
                global_stale = any(
                    pin["expected"][name] is not None and not pin["matches"][name]
                    for name in pin["matches"]
                )
                if signature_stale:
                    status = "stale"
                    reason = (
                        "Rust signature differs from the ledger's reviewed signature"
                    )
                elif global_stale:
                    status = "stale"
                    reason = (
                        "Rust or Python surface pin differs from the ledger baseline"
                    )
                elif target_info is None:
                    status = "stale"
                    reason = (
                        "mapped Python target is absent from live package introspection"
                    )
                elif (
                    mapping_problem := _mapping_configuration_problem(
                        item, entry, target_info, python["targets"]
                    )
                ) is not None:
                    status = "missing"
                    reason = f"incomplete argument mapping: {mapping_problem}"
                elif stale_evidence.get(item["symbolKey"]):
                    status = "stale"
                    reason = (
                        "available conformance evidence is bound to an older "
                        "surface snapshot"
                    )
                else:
                    item_evidence = evidence_by_item.get(item["symbolKey"], [])
                    if item_evidence:
                        status = "verified"
                        reason = (
                            "matching executed conformance evidence is bound "
                            "to this snapshot"
                        )
                    else:
                        status = "mapped"
                        reason = (
                            "target and mapping are declared; no matching "
                            "executed conformance evidence"
                        )

        report_items.append(
            {
                **item,
                "status": status,
                "statusReason": reason,
                "python": (
                    {
                        "target": entry.get("pythonTarget"),
                        "targetKind": target_info.get("kind") if target_info else None,
                        "signature": target_info.get("signature")
                        if target_info
                        else None,
                        "fields": target_info.get("fields", []) if target_info else [],
                        "alias": target_info.get("alias") if target_info else None,
                        "value": target_info.get("value") if target_info else None,
                    }
                    if entry and entry.get("decision") == "mapped"
                    else None
                ),
                "mapping": (
                    {
                        "decision": entry.get("decision"),
                        "mappingDirection": entry.get("mappingDirection"),
                        "pythonTarget": entry.get("pythonTarget"),
                        "semanticEquivalent": entry.get("semanticEquivalent"),
                        "variantBinding": entry.get("variantBinding"),
                        "outputBinding": entry.get("outputBinding"),
                        "receiverMapping": entry.get("receiverMapping"),
                        "fixedArguments": entry.get("fixedArguments"),
                        "argumentMappings": entry.get("argumentMappings", []),
                        "defaults": entry.get("defaults", []),
                        "units": entry.get("units", []),
                        "cardinality": entry.get("cardinality", []),
                        "rationale": entry.get("rationale"),
                        "review": entry.get("review"),
                    }
                    if entry
                    else None
                ),
                "evidence": item_evidence,
            }
        )

    counts = Counter(item["status"] for item in report_items)
    denominator = len(report_items)
    covered = counts["verified"] + counts["language-specific"]
    if (
        stale_ledger_entries
        or counts["stale"]
        or (pin["pinned"] and not pin["matchesAll"])
    ):
        parity_status = "stale"
    elif denominator > 0 and covered == denominator and pin["matchesAll"]:
        parity_status = "complete"
    else:
        parity_status = "incomplete"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "python-rust-sdk-parity-report",
        "toolVersion": TOOL_VERSION,
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "revision": rust["sourceRevision"],
            "sdk": rust["sdk"],
            "reference": rust["reference"],
            "inventorySignature": rust["inventorySignature"],
            "featureProfile": rust["featureProfile"],
            "featureProfileDigest": rust["featureProfileDigest"],
        },
        "python": {
            "package": python["package"],
            "runtime": python["runtime"],
            "surfaceDigest": python["surfaceDigest"],
            "implementationDigest": python["implementationDigest"],
            "objects": python["objects"],
            "targets": python["targets"],
        },
        "ledger": {
            "sourceRevision": pin["expected"]["sourceRevision"],
            "inventorySignature": pin["expected"]["inventorySignature"],
            "featureProfileDigest": pin["expected"]["featureProfileDigest"],
            "pythonSurfaceDigest": pin["expected"]["pythonSurfaceDigest"],
            "pythonImplementationDigest": pin["expected"]["pythonImplementationDigest"],
            "pinState": pin,
            "staleEntries": stale_ledger_entries,
        },
        "parityStatus": parity_status,
        "coverage": {
            "denominator": denominator,
            "counts": {status: counts[status] for status in sorted(STATUS_VALUES)},
            "covered": covered,
            "mappedButUnverified": counts["mapped"],
            "staleOrMissing": counts["stale"] + counts["missing"],
            "items": report_items,
        },
    }


def strict_failures(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    pin = report["ledger"]["pinState"]
    if not pin["pinned"]:
        failures.append(
            "ledger baseline is not fully pinned to Rust and Python surfaces"
        )
    elif not pin["matchesAll"]:
        failures.append(
            "ledger baseline does not match the current source and feature profile"
        )
    if report["ledger"]["staleEntries"]:
        failures.append("ledger contains paths absent from the current Rust inventory")
    counts = report["coverage"]["counts"]
    if counts["missing"]:
        failures.append(
            f"{counts['missing']} public Rust symbols or members are unmapped"
        )
    if counts["stale"]:
        failures.append(f"{counts['stale']} mappings or evidence records are stale")
    if counts["mapped"]:
        failures.append(f"{counts['mapped']} mappings lack conformance evidence")
    return failures


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def summary_from_report(report: dict[str, Any], report_sha256: str) -> dict[str, Any]:
    """A small frontend artifact derived from the full evidence-backed report."""
    summary = {
        "schemaVersion": 1,
        "kind": "python-rust-sdk-parity-summary",
        "generatedAt": report["generatedAt"],
        "parityStatus": report["parityStatus"],
        "source": report["source"],
        "python": {
            key: report["python"][key]
            for key in ("package", "runtime", "surfaceDigest", "implementationDigest")
        },
        "pinsMatch": report["ledger"]["pinState"]["matchesAll"],
        "coverage": {
            key: report["coverage"][key]
            for key in (
                "denominator",
                "counts",
                "covered",
                "mappedButUnverified",
                "staleOrMissing",
            )
        },
        "reportSha256": report_sha256,
        "provenance": "unsigned-local-validation",
    }
    if "sdkParity" in report:
        summary["gate"] = "sdk"
        summary["inventoryParityStatus"] = report["inventoryParityStatus"]
        sdk = report["sdkParity"]
        summary["sdkParity"] = {
            key: sdk[key]
            for key in (
                "schemaVersion",
                "kind",
                "parityStatus",
                "counts",
                "mechanicCounts",
            )
            if key in sdk
        }
        summary["sdkParity"]["mappingStatus"] = {
            key: value
            for key, value in sdk.get("mappingStatus", {}).items()
            if not key.endswith("Ids")
        }
        summary["sdkParity"]["behaviorStatus"] = {
            key: value
            for key, value in sdk.get("behaviorStatus", {}).items()
            if key in {"passed", "requiredSuites", "suites"}
        }
        summary["sdkParity"]["individualItemEvidence"] = {
            key: value
            for key, value in sdk.get("individualItemEvidence", {}).items()
            if not key.endswith("Ids")
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument("--python-root", type=Path, default=Path("python"))
    parser.add_argument("--package", default="yosoi")
    parser.add_argument("--locale", default="en")
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--gate", choices=("inventory", "sdk"), default="inventory")
    parser.add_argument(
        "--contract", type=Path, default=Path("python/parity/sdk-contract.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("python/parity/report.json")
    )
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="write an incomplete inventory report with exit status zero",
    )
    args = parser.parse_args(argv)
    try:
        rust = load_rust_inventory(args.rust_reference, args.locale)
        python = introspect_python_package(args.package, args.python_root)
        ledger = load_ledger(args.ledger)
        contract = None
        drift = []
        if args.gate == "sdk":
            import sdk_contract

            contract = sdk_contract.load_contract(args.contract)
            ledger, drift = sdk_contract.prepare_ledger(contract, rust, python, ledger)
        evidence = [_load_evidence(path, rust, python) for path in args.evidence]
        report = build_report(rust, python, ledger, evidence)
        if contract is not None:
            sdk_report = sdk_contract.evaluate_contract(
                contract, rust, python, report, evidence, drift
            )
            report["gate"] = "sdk"
            report["inventoryParityStatus"] = report["parityStatus"]
            report["sdkParity"] = sdk_report
            report["parityStatus"] = sdk_report["parityStatus"]
        write_report(args.output, report)
        if args.summary_output is not None:
            write_report(
                args.summary_output,
                summary_from_report(report, digest_bytes(args.output.read_bytes())),
            )
    except ValueError as error:
        parser.error(str(error))
    failures = (
        sdk_contract.sdk_failures(report["sdkParity"])
        if contract is not None
        else strict_failures(report)
    )
    counts = report["coverage"]["counts"]
    print(
        f"{report['parityStatus']}: {report['coverage']['denominator']} Rust items; "
        f"{counts['verified']} verified, {counts['mapped']} mapped, "
        f"{counts['language-specific']} language-specific, "
        f"{counts['missing']} missing, "
        f"{counts['stale']} stale; report={args.output}"
    )
    if failures and not args.allow_incomplete:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

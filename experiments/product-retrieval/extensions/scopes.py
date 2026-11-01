"""Evaluate URL-reference eligibility under explicitly named scope policies.

This module is an offline experiment. Eligibility describes URL membership only;
it does not establish source correctness, trust, retrieval quality, or permission
to navigate to a URL. Registrable-domain evaluation uses a locally retained
Public Suffix List snapshot and never fetches data during import or evaluation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import ipaddress
import json
import platform
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote_to_bytes, urlsplit

ScopeMode = Literal[
    "exactpage",
    "samehost",
    "sameorigin",
    "registrable-domain",
    "unrestricted",
]
QueryBehavior = Literal["include", "ignore", "keys"]
FragmentBehavior = Literal["include", "ignore"]

PRIMARY_PSL_SOURCE = "https://publicsuffix.org/list/public_suffix_list.dat"
PINNED_IDNA_VERSION = "3.10"
DEFAULT_SNAPSHOT_DIR = (
    Path(__file__).resolve().parents[3] / ".generated" / "product-retrieval-scopes"
)
_ASCII_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
_HEX = frozenset("0123456789abcdefABCDEF")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_PATH_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~/!$&'()*+,;=:@"
)
_QUERY_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~/?!$&'()*+,;=:@"
)
_FRAGMENT_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~/?!$&'()*+,;=:@"
)


@dataclass(frozen=True)
class ScopePolicy:
    """Declare how a reference URL is compared with a seed URL.

    ``url-v1`` normalization lowercases schemes and DNS names, converts
    internationalized hostnames to ASCII using optional ``idna==3.10``,
    removes default ports, gives empty paths ``/``, normalizes percent escapes,
    and removes dot segments. Query and fragment handling is controlled by
    their separate policy fields. The normalizer rejects URL credentials and
    non-HTTP(S) schemes as unknown rather than treating them as matches.

    Registrable-domain policies require explicit scheme sensitivity and a
    choice to include private PSL rules. They compare registrable domains and
    intentionally ignore ports. Other modes must leave those fields unset.
    """

    mode: ScopeMode
    normalization: Literal["url-v1"] = "url-v1"
    query_behavior: QueryBehavior = "include"
    query_keys: tuple[str, ...] = ()
    fragment_behavior: FragmentBehavior = "ignore"
    scheme_sensitive: bool | None = None
    include_private_suffixes: bool | None = None

    def __post_init__(self) -> None:
        if self.mode not in {
            "exactpage",
            "samehost",
            "sameorigin",
            "registrable-domain",
            "unrestricted",
        }:
            raise ValueError(f"unsupported scope mode: {self.mode!r}")
        if self.normalization != "url-v1":
            raise ValueError(f"unsupported URL normalization: {self.normalization!r}")
        if self.query_behavior not in {"include", "ignore", "keys"}:
            raise ValueError(f"unsupported query behavior: {self.query_behavior!r}")
        if self.fragment_behavior not in {"include", "ignore"}:
            raise ValueError(
                f"unsupported fragment behavior: {self.fragment_behavior!r}"
            )
        if not isinstance(self.query_keys, tuple):
            raise ValueError("query_keys must be an immutable tuple")
        if self.query_behavior == "keys" and any(
            not isinstance(key, str) for key in self.query_keys
        ):
            raise ValueError("query_keys must contain only strings")
        if self.query_behavior != "keys" and self.query_keys:
            raise ValueError("query_keys are only valid with query_behavior='keys'")
        if self.mode != "exactpage" and (
            self.query_behavior != "include"
            or self.query_keys
            or self.fragment_behavior != "ignore"
        ):
            raise ValueError("query and fragment behavior only apply to exactpage")
        if self.mode == "registrable-domain":
            if not isinstance(self.scheme_sensitive, bool):
                raise ValueError(
                    "registrable-domain requires an explicit scheme_sensitive bool"
                )
            if not isinstance(self.include_private_suffixes, bool):
                raise ValueError(
                    "registrable-domain requires an explicit "
                    "include_private_suffixes bool"
                )
        elif (
            self.scheme_sensitive is not None
            or self.include_private_suffixes is not None
        ):
            raise ValueError(
                "scheme_sensitive and include_private_suffixes only apply to "
                "registrable-domain"
            )


@dataclass(frozen=True)
class ReferenceDecision:
    """Record one candidate URL's eligibility and the reason for that result."""

    url: str
    eligible: bool | None
    reason: str
    normalized_url: str | None = None


@dataclass(frozen=True)
class ScopeEvaluation:
    """Return the eligible URLs and a decision for every supplied reference."""

    policy: ScopePolicy
    seed_url: str
    eligible_references: tuple[str, ...]
    decisions: tuple[ReferenceDecision, ...]


@dataclass(frozen=True)
class _NormalizedUrl:
    original: str
    scheme: str
    host: str
    is_ipv6: bool
    explicit_port: int | None
    effective_port: int
    path: str
    query: str
    fragment: str

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if self.is_ipv6 else self.host
        default_port = 80 if self.scheme == "http" else 443
        if self.explicit_port is not None and self.explicit_port != default_port:
            return f"{host}:{self.explicit_port}"
        return host

    @property
    def normalized_url(self) -> str:
        result = f"{self.scheme}://{self.authority}{self.path}"
        if self.query:
            result += f"?{self.query}"
        if self.fragment:
            result += f"#{self.fragment}"
        return result


@dataclass(frozen=True)
class SuffixList:
    """Parsed exact, wildcard, and exception rules from a PSL snapshot."""

    public_exact: frozenset[str]
    private_exact: frozenset[str]
    public_wildcard: frozenset[str]
    private_wildcard: frozenset[str]
    public_exception: frozenset[str]
    private_exception: frozenset[str]

    @classmethod
    def from_text(cls, text: str) -> SuffixList:
        """Parse a PSL-formatted string while retaining its private section."""
        exact_public: set[str] = set()
        exact_private: set[str] = set()
        wildcard_public: set[str] = set()
        wildcard_private: set[str] = set()
        exception_public: set[str] = set()
        exception_private: set[str] = set()
        private = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line == "// ===BEGIN PRIVATE DOMAINS===":
                private = True
                continue
            if not line or line.startswith("//"):
                continue
            is_exception = line.startswith("!")
            is_wildcard = line.startswith("*.")
            rule = line[1:] if is_exception else line[2:] if is_wildcard else line
            ascii_rule, error = _idna_ascii(rule)
            if error in {"idna_support_unavailable", "idna_version_not_pinned"}:
                # PSL snapshot rules are trusted source data. The stdlib codec
                # lets this parser retain Unicode rules without adding an
                # import-time dependency. Unicode and A-label input URLs remain
                # unknown unless the optional IDNA package is available.
                try:
                    ascii_rule = rule.encode("idna").decode("ascii").lower()
                    error = None
                except UnicodeError:
                    ascii_rule = None
            if error is not None or ascii_rule is None:
                raise ValueError(f"invalid public suffix rule {line!r}: {error}")
            if is_exception:
                (exception_private if private else exception_public).add(ascii_rule)
            elif is_wildcard:
                (wildcard_private if private else wildcard_public).add(ascii_rule)
            else:
                (exact_private if private else exact_public).add(ascii_rule)
        return cls(
            public_exact=frozenset(exact_public),
            private_exact=frozenset(exact_private),
            public_wildcard=frozenset(wildcard_public),
            private_wildcard=frozenset(wildcard_private),
            public_exception=frozenset(exception_public),
            private_exception=frozenset(exception_private),
        )

    def registrable_domain(
        self, host: str, *, include_private_suffixes: bool
    ) -> str | None:
        """Return eTLD+1, or ``None`` when the snapshot cannot establish one."""
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        labels = host.split(".")
        if len(labels) < 2:
            return None
        exact = set(self.public_exact)
        wildcard = set(self.public_wildcard)
        exceptions = set(self.public_exception)
        if include_private_suffixes:
            exact.update(self.private_exact)
            wildcard.update(self.private_wildcard)
            exceptions.update(self.private_exception)

        exception_lengths = [
            len(rule.split("."))
            for rule in exceptions
            if _ends_with_labels(labels, rule.split("."))
        ]
        if exception_lengths:
            public_suffix_length = max(exception_lengths) - 1
        else:
            exact_lengths = [
                len(rule.split("."))
                for rule in exact
                if _ends_with_labels(labels, rule.split("."))
            ]
            wildcard_lengths = [
                len(rule.split(".")) + 1
                for rule in wildcard
                if len(labels) > len(rule.split("."))
                and _ends_with_labels(labels, rule.split("."))
            ]
            matches = exact_lengths + wildcard_lengths
            if not matches:
                return None
            public_suffix_length = max(matches)
        if len(labels) <= public_suffix_length:
            return None
        return ".".join(labels[-(public_suffix_length + 1) :])


def _ends_with_labels(host_labels: list[str], suffix_labels: list[str]) -> bool:
    return (
        len(host_labels) >= len(suffix_labels)
        and host_labels[-len(suffix_labels) :] == suffix_labels
    )


def _idna_ascii(host: str) -> tuple[str | None, str | None]:
    """Validate DNS labels and use only the pinned optional IDNA version."""
    if not host:
        return None, "empty_host"
    if host.endswith("."):
        host = host[:-1]
    if not host or host.endswith("."):
        return None, "invalid_trailing_dot"
    try:
        idna = importlib.import_module("idna")
    except ImportError:
        idna = None
    if idna is not None and getattr(idna, "__version__", None) != PINNED_IDNA_VERSION:
        idna = None
        idna_error = "idna_version_not_pinned"
    else:
        idna_error = "idna_support_unavailable"
    if not host.isascii() and idna is None:
        return None, idna_error
    if idna is None and any(
        label.lower().startswith("xn--") for label in host.split(".")
    ):
        return None, f"{idna_error}_for_alabel"
    try:
        if idna is not None:
            encoded = idna.encode(host, uts46=False, std3_rules=True).decode("ascii")
        elif host.isascii():
            encoded = host.encode("ascii").decode("ascii")
        else:
            return None, "idna_support_unavailable"
    except (UnicodeError, ValueError) as exc:
        return None, f"invalid_idna_host:{type(exc).__name__}"
    normalized = encoded.lower()
    if len(normalized) > 253:
        return None, "hostname_too_long"
    labels = normalized.split(".")
    if not labels or any(_ASCII_LABEL.fullmatch(label) is None for label in labels):
        return None, "invalid_dns_label"
    return normalized, None


def _normalize_host(host: str) -> tuple[str | None, bool, str | None]:
    if "%" in host:
        return None, False, "ipv6_zone_or_percent_host_not_supported"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host:
            return None, False, "invalid_ipv6_address"
        if re.fullmatch(r"[0-9.]+", host):
            return None, False, "invalid_or_ambiguous_ipv4_address"
        ascii_host, error = _idna_ascii(host)
        return ascii_host, False, error
    if isinstance(address, ipaddress.IPv6Address):
        return address.compressed.lower(), True, None
    return str(address), False, None


def _normalize_component(
    value: str, safe: frozenset[str]
) -> tuple[str | None, str | None]:
    pieces: list[str] = []
    position = 0
    while position < len(value):
        character = value[position]
        if character == "%":
            if (
                position + 2 >= len(value)
                or value[position + 1] not in _HEX
                or value[position + 2] not in _HEX
            ):
                return None, "invalid_percent_escape"
            byte = int(value[position + 1 : position + 3], 16)
            decoded = chr(byte)
            if decoded in _UNRESERVED:
                pieces.append(decoded)
            else:
                pieces.append(f"%{byte:02X}")
            position += 3
            continue
        if ord(character) < 128:
            pieces.append(character if character in safe else f"%{ord(character):02X}")
        else:
            pieces.extend(f"%{byte:02X}" for byte in character.encode("utf-8"))
        position += 1
    return "".join(pieces), None


def _remove_dot_segments(path: str) -> str:
    segments = path.split("/")
    output: list[str] = []
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if segment == ".":
            if is_last:
                output.append("")
            continue
        if segment == "..":
            if output and output[-1] != "":
                output.pop()
            elif len(output) > 1:
                output.pop()
            if is_last:
                output.append("")
            continue
        output.append(segment)
    result = "/".join(output)
    return result or "/"


def _parse_url(value: object) -> tuple[_NormalizedUrl | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, "empty_or_non_string_url"
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        return None, "url_contains_whitespace_or_control"
    if "\\" in value:
        return None, "backslash_not_supported_in_url"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None, "invalid_url_syntax"
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None, "unsupported_scheme"
    if not parsed.netloc:
        return None, "missing_authority"
    if parsed.netloc.endswith(":"):
        return None, "empty_port"
    if parsed.username is not None or parsed.password is not None:
        return None, "credentials_not_supported"
    try:
        raw_host = parsed.hostname
        explicit_port = parsed.port
    except ValueError:
        return None, "invalid_port_or_authority"
    if raw_host is None:
        return None, "missing_host"
    host, is_ipv6, host_error = _normalize_host(raw_host)
    if host_error is not None or host is None:
        return None, host_error or "invalid_host"
    if explicit_port is not None and not 1 <= explicit_port <= 65535:
        return None, "invalid_port"
    default_port = 80 if scheme == "http" else 443
    effective_port = explicit_port if explicit_port is not None else default_port
    path, error = _normalize_component(parsed.path or "/", _PATH_SAFE)
    if error is not None or path is None:
        return None, error or "invalid_path"
    path = _remove_dot_segments(path)
    query, error = _normalize_component(parsed.query, _QUERY_SAFE)
    if error is not None or query is None:
        return None, error or "invalid_query"
    fragment, error = _normalize_component(parsed.fragment, _FRAGMENT_SAFE)
    if error is not None or fragment is None:
        return None, error or "invalid_fragment"
    return (
        _NormalizedUrl(
            original=value,
            scheme=scheme,
            host=host,
            is_ipv6=is_ipv6,
            explicit_port=explicit_port,
            effective_port=effective_port,
            path=path,
            query=query,
            fragment=fragment,
        ),
        None,
    )


def _query_for_policy(query: str, policy: ScopePolicy) -> tuple[str | None, str | None]:
    if policy.query_behavior == "ignore":
        return "", None
    if policy.query_behavior == "include":
        return query, None
    if policy.query_behavior != "keys":
        return None, "unsupported_query_behavior"
    wanted = frozenset(policy.query_keys)
    kept: list[str] = []
    if not query:
        return "", None
    for part in query.split("&"):
        key = part.split("=", 1)[0].replace("+", " ")
        try:
            decoded_key = unquote_to_bytes(key).decode("utf-8", errors="strict")
        except UnicodeError:
            return None, "invalid_query_key_encoding"
        if decoded_key in wanted:
            kept.append(part)
    return "&".join(kept), None


def _page_key(
    url: _NormalizedUrl, policy: ScopePolicy
) -> tuple[tuple[str, str, int, str, str, str] | None, str | None]:
    query, error = _query_for_policy(url.query, policy)
    if error is not None or query is None:
        return None, error
    fragment = url.fragment if policy.fragment_behavior == "include" else ""
    return (
        (
            url.scheme,
            url.host,
            url.effective_port,
            url.path,
            query,
            fragment,
        ),
        None,
    )


def _same_result(
    seed: _NormalizedUrl,
    reference: _NormalizedUrl,
    policy: ScopePolicy,
    suffixes: SuffixList | None,
) -> tuple[bool | None, str]:
    if policy.mode == "unrestricted":
        return True, "valid_http_url_unrestricted"
    if policy.mode == "samehost":
        matched = seed.host == reference.host
        return matched, "same_normalized_host" if matched else "different_host"
    if policy.mode == "sameorigin":
        matched = (
            seed.scheme == reference.scheme
            and seed.host == reference.host
            and seed.effective_port == reference.effective_port
        )
        return matched, "same_origin" if matched else "different_origin"
    if policy.mode == "exactpage":
        seed_key, seed_error = _page_key(seed, policy)
        reference_key, reference_error = _page_key(reference, policy)
        if seed_error is not None or reference_error is not None:
            return None, seed_error or reference_error or "page_comparison_unknown"
        matched = seed_key == reference_key
        return (
            matched,
            "same_normalized_page" if matched else "different_normalized_page",
        )
    if policy.mode == "registrable-domain":
        if suffixes is None:
            return None, "public_suffix_snapshot_unavailable"
        if policy.scheme_sensitive and seed.scheme != reference.scheme:
            return False, "different_scheme"
        seed_domain = suffixes.registrable_domain(
            seed.host, include_private_suffixes=bool(policy.include_private_suffixes)
        )
        reference_domain = suffixes.registrable_domain(
            reference.host,
            include_private_suffixes=bool(policy.include_private_suffixes),
        )
        if seed_domain is None:
            return None, "seed_registrable_domain_unknown"
        if reference_domain is None:
            return None, "reference_registrable_domain_unknown"
        matched = seed_domain == reference_domain
        return (
            matched,
            "same_registrable_domain" if matched else "different_registrable_domain",
        )
    return None, "unsupported_scope_mode"


def evaluate_references(
    seed_url: str,
    reference_urls: list[str] | tuple[str, ...],
    policy: ScopePolicy,
    *,
    suffixes: SuffixList | None = None,
) -> ScopeEvaluation:
    """Evaluate every URL and preserve explicit unknowns in the result.

    Invalid references and invalid seeds are never silently treated as eligible.
    The returned ``eligible_references`` includes only decisions whose value is
    exactly ``True``; a ``None`` decision is an explicit unknown.
    """
    seed, seed_error = _parse_url(seed_url)
    if policy.mode == "registrable-domain" and suffixes is None:
        try:
            suffixes, _ = load_suffix_snapshot()
        except (OSError, ValueError, json.JSONDecodeError):
            suffixes = None
    decisions: list[ReferenceDecision] = []
    for value in reference_urls:
        display = value if isinstance(value, str) else repr(value)
        reference, reference_error = _parse_url(value)
        if seed_error is not None or seed is None:
            decisions.append(
                ReferenceDecision(
                    url=display,
                    eligible=None,
                    reason=f"invalid_seed:{seed_error or 'invalid_url'}",
                )
            )
            continue
        if reference_error is not None or reference is None:
            decisions.append(
                ReferenceDecision(
                    url=display,
                    eligible=None,
                    reason=f"invalid_reference:{reference_error or 'invalid_url'}",
                )
            )
            continue
        eligible, reason = _same_result(seed, reference, policy, suffixes)
        decisions.append(
            ReferenceDecision(
                url=display,
                eligible=eligible,
                reason=reason,
                normalized_url=reference.normalized_url,
            )
        )
    eligible_references = tuple(
        decision.url for decision in decisions if decision.eligible is True
    )
    return ScopeEvaluation(
        policy=policy,
        seed_url=seed_url,
        eligible_references=eligible_references,
        decisions=tuple(decisions),
    )


def load_suffix_snapshot(
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
) -> tuple[SuffixList, dict[str, object]]:
    """Load and verify the retained PSL bytes and their acquisition record."""
    data_path = snapshot_dir / "public_suffix_list.dat"
    metadata_path = snapshot_dir / "public_suffix_list.provenance.json"
    raw = data_path.read_bytes()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("format") != "public-suffix-list-snapshot-v1":
        raise ValueError("unrecognized Public Suffix List provenance format")
    if metadata.get("source_url") != PRIMARY_PSL_SOURCE:
        raise ValueError("PSL provenance does not name publicsuffix.org as its source")
    if metadata.get("final_url") != PRIMARY_PSL_SOURCE:
        raise ValueError("PSL provenance final URL is not the primary source")
    actual_hash = hashlib.sha256(raw).hexdigest()
    if metadata.get("sha256") != actual_hash:
        raise ValueError("PSL snapshot SHA-256 does not match its provenance")
    if metadata.get("byte_len") != len(raw):
        raise ValueError("PSL snapshot byte length does not match its provenance")
    text = raw.decode("utf-8", errors="strict")
    return SuffixList.from_text(text), metadata


def _idna_runtime_provenance() -> dict[str, str | None]:
    """Describe the optional IDNA runtime without importing it at module load."""
    try:
        idna = importlib.import_module("idna")
    except ImportError:
        return {
            "package": "idna",
            "source_url": "https://github.com/kjd/idna",
            "pinned_version": PINNED_IDNA_VERSION,
            "loaded_version": None,
            "url_host_behavior": (
                "Unicode and A-label hostnames are unknown without the pinned package."
            ),
        }
    version = getattr(idna, "__version__", None)
    return {
        "package": "idna",
        "source_url": "https://github.com/kjd/idna",
        "pinned_version": PINNED_IDNA_VERSION,
        "loaded_version": str(version) if version is not None else None,
        "url_host_behavior": (
            "Pinned IDNA validation is active."
            if version == PINNED_IDNA_VERSION
            else (
                "Unicode and A-label hostnames are unknown because "
                "the installed version is not pinned."
            )
        ),
    }


def _policy_catalog() -> tuple[tuple[str, ScopePolicy], ...]:
    return (
        ("exactpage_query_fragment_ignored", ScopePolicy("exactpage")),
        (
            "exactpage_query_and_fragment_included",
            ScopePolicy("exactpage", fragment_behavior="include"),
        ),
        (
            "exactpage_query_ignored",
            ScopePolicy("exactpage", query_behavior="ignore"),
        ),
        (
            "exactpage_variant_query_only",
            ScopePolicy("exactpage", query_behavior="keys", query_keys=("variant",)),
        ),
        ("samehost", ScopePolicy("samehost")),
        ("sameorigin", ScopePolicy("sameorigin")),
        (
            "registrable_public_scheme_insensitive",
            ScopePolicy(
                "registrable-domain",
                scheme_sensitive=False,
                include_private_suffixes=False,
            ),
        ),
        (
            "registrable_public_scheme_sensitive",
            ScopePolicy(
                "registrable-domain",
                scheme_sensitive=True,
                include_private_suffixes=False,
            ),
        ),
        (
            "registrable_private_scheme_insensitive",
            ScopePolicy(
                "registrable-domain",
                scheme_sensitive=False,
                include_private_suffixes=True,
            ),
        ),
        ("unrestricted", ScopePolicy("unrestricted")),
    )


def _actual_urls(root: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    manifest_path = root / ".generated" / "product-retrieval-fresh" / "manifest.json"
    provenance_path = (
        root
        / "experiments"
        / "contract-fingerprints"
        / "fixtures"
        / "evidence"
        / "provenance.json"
    )
    manifest_raw = manifest_path.read_bytes()
    provenance_raw = provenance_path.read_bytes()
    manifest = json.loads(manifest_raw)
    provenance = json.loads(provenance_raw)
    rows: list[dict[str, str]] = []
    for page in manifest.get("pages", []):
        page_id = str(page.get("id", "unknown"))
        requested = page.get("requested_url")
        final = page.get("final_url")
        if isinstance(requested, str):
            rows.append({"id": f"fresh:{page_id}:requested", "url": requested})
        if isinstance(final, str) and final != requested:
            rows.append({"id": f"fresh:{page_id}:final", "url": final})
    for capture in provenance.get("captures", []):
        capture_id = str(capture.get("id", "unknown"))
        capture_url = capture.get("url")
        if isinstance(capture_url, str):
            rows.append({"id": f"capture:{capture_id}", "url": capture_url})
    oracle_url = provenance.get("oracle_url")
    if isinstance(oracle_url, str):
        rows.append({"id": "capture:oracle", "url": oracle_url})
    source_hashes = {
        str(manifest_path.relative_to(root)): hashlib.sha256(manifest_raw).hexdigest(),
        str(provenance_path.relative_to(root)): hashlib.sha256(
            provenance_raw
        ).hexdigest(),
    }
    return rows, source_hashes


def _control_pairs() -> list[dict[str, str]]:
    return [
        {
            "id": "samehost_different_path",
            "seed_url": "https://shop.example.test/products/1",
            "reference_url": "https://shop.example.test/products/2",
        },
        {
            "id": "subdomain_same_registrable_domain",
            "seed_url": "https://www.example.com/item",
            "reference_url": "https://shop.example.com/other",
        },
        {
            "id": "co_uk_registrable_domain",
            "seed_url": "https://a.example.co.uk/item",
            "reference_url": "https://b.example.co.uk/other",
        },
        {
            "id": "private_suffix_tenant_boundary",
            "seed_url": "https://tenant-a.blogspot.com/item",
            "reference_url": "https://tenant-b.blogspot.com/other",
        },
        {
            "id": "ip_same_host_different_page",
            "seed_url": "http://192.0.2.10/products/1",
            "reference_url": "http://192.0.2.10/products/2",
        },
        {
            "id": "scheme_change_same_host",
            "seed_url": "http://example.com/item",
            "reference_url": "https://example.com/item",
        },
        {
            "id": "query_parameter_change",
            "seed_url": "https://example.com/item?id=1&variant=red#details",
            "reference_url": "https://example.com/item?id=2&variant=red#other",
        },
        {
            "id": "fragment_change_only",
            "seed_url": "https://example.com/item?id=1#details",
            "reference_url": "https://example.com/item?id=1#other",
        },
        {
            "id": "suffix_lookalike_not_same_domain",
            "seed_url": "https://paypal.com/account",
            "reference_url": "https://paypal.com.evil.test/account",
        },
        {
            "id": "local_hostname_no_registrable_domain",
            "seed_url": "http://localhost:8000/item",
            "reference_url": "http://localhost:8001/other",
        },
        {
            "id": "invalid_port_unknown",
            "seed_url": "https://example.com:99999/item",
            "reference_url": "https://example.com/item",
        },
        {
            "id": "empty_url_unknown",
            "seed_url": "https://example.com/item",
            "reference_url": "",
        },
        {
            "id": "idna_unicode_and_alabel_equivalence",
            "seed_url": "https://bücher.example/item",
            "reference_url": "https://xn--bcher-kva.example/item",
        },
        {
            "id": "idna_sharp_s_differs_from_ss",
            "seed_url": "https://faß.de/item",
            "reference_url": "https://fass.de/item",
        },
        {
            "id": "idna_invalid_ascii_label_unknown",
            "seed_url": "https://example.com/item",
            "reference_url": "https://-bad.example/item",
        },
        {
            "id": "idna_invalid_alabel_unknown",
            "seed_url": "https://example.com/item",
            "reference_url": "https://xn--.example/item",
        },
    ]


def run_scope_matrix(root: Path, destination: Path) -> dict[str, object]:
    """Write a small URL-only eligibility matrix from retained source URLs."""
    suffixes, psl_metadata = load_suffix_snapshot()
    actual, source_hashes = _actual_urls(root)
    policies = _policy_catalog()
    pairs: list[dict[str, str]] = []
    for seed in actual:
        for reference in actual:
            pairs.append(
                {
                    "case_id": "actual_source_cross_product",
                    "seed_id": seed["id"],
                    "reference_id": reference["id"],
                    "seed_url": seed["url"],
                    "reference_url": reference["url"],
                }
            )
    for control in _control_pairs():
        pairs.append(
            {
                "case_id": control["id"],
                "seed_id": f"control:{control['id']}:seed",
                "reference_id": f"control:{control['id']}:reference",
                "seed_url": control["seed_url"],
                "reference_url": control["reference_url"],
            }
        )

    destination.mkdir(parents=True, exist_ok=True)
    matrix_path = destination / "scope-eligibility-matrix.csv"
    fields = [
        "case_id",
        "seed_id",
        "reference_id",
        "seed_url",
        "reference_url",
        "policy_id",
        "policy_json",
        "eligible",
        "reason",
        "normalized_reference_url",
    ]
    totals: dict[str, dict[str, object]] = {
        policy_id: {
            "total": 0,
            "eligible": 0,
            "ineligible": 0,
            "unknown": 0,
            "counterexamples_vs_exactpage": [],
        }
        for policy_id, _ in policies
    }
    control_results: dict[str, dict[str, dict[str, str]]] = {}
    with matrix_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for pair in pairs:
            exactpage_decision: ReferenceDecision | None = None
            for policy_id, policy in policies:
                result = evaluate_references(
                    pair["seed_url"],
                    [pair["reference_url"]],
                    policy,
                    suffixes=suffixes,
                )
                decision = result.decisions[0]
                row = {
                    **pair,
                    "policy_id": policy_id,
                    "policy_json": json.dumps(asdict(policy), sort_keys=True),
                    "eligible": "unknown"
                    if decision.eligible is None
                    else str(decision.eligible).lower(),
                    "reason": decision.reason,
                    "normalized_reference_url": decision.normalized_url or "",
                }
                writer.writerow(row)
                tally = totals[policy_id]
                tally["total"] = int(tally["total"]) + 1
                key = (
                    "unknown"
                    if decision.eligible is None
                    else "eligible"
                    if decision.eligible
                    else "ineligible"
                )
                tally[key] = int(tally[key]) + 1
                if pair["case_id"] != "actual_source_cross_product":
                    control_results.setdefault(pair["case_id"], {})[policy_id] = {
                        "eligible": "unknown"
                        if decision.eligible is None
                        else str(decision.eligible).lower(),
                        "reason": decision.reason,
                    }
                if policy_id == "exactpage_query_fragment_ignored":
                    exactpage_decision = decision
                elif (
                    decision.eligible is True
                    and exactpage_decision is not None
                    and exactpage_decision.eligible is False
                ):
                    examples = tally["counterexamples_vs_exactpage"]
                    if isinstance(examples, list) and len(examples) < 5:
                        examples.append(
                            {
                                "case_id": pair["case_id"],
                                "seed_url": pair["seed_url"],
                                "reference_url": pair["reference_url"],
                                "reason": decision.reason,
                                "note": "scope disagreement only; no correctness label",
                            }
                        )
    summary = {
        "format": "product-retrieval-url-scope-matrix-v1",
        "purpose": (
            "Compare declared URL membership policies only; no "
            "retrieval, scoring, gold targets, or correctness "
            "labels are used."
        ),
        "normalization": "url-v1",
        "actual_url_count": len(actual),
        "actual_source_ids": [row["id"] for row in actual],
        "pair_count": len(pairs),
        "python_version": platform.python_version(),
        "policies": {
            policy_id: {"policy": asdict(policy), **totals[policy_id]}
            for policy_id, policy in policies
        },
        "inputs": {
            **source_hashes,
            "idna_runtime": _idna_runtime_provenance(),
            "public_suffix_list_sha256": psl_metadata["sha256"],
            "public_suffix_list_version_comment": psl_metadata.get("version_comment"),
            "public_suffix_list_source": psl_metadata.get("source_url"),
            "public_suffix_list_retrieved_at_utc": psl_metadata.get("retrieved_at_utc"),
        },
        "control_ids": [control["id"] for control in _control_pairs()],
        "control_results": control_results,
        "idna_control_counts": {
            policy_id: {
                state: sum(
                    1
                    for control_id, outcomes in control_results.items()
                    if control_id.startswith("idna_")
                    and outcomes.get(policy_id, {}).get("eligible") == value
                )
                for state, value in (
                    ("eligible", "true"),
                    ("ineligible", "false"),
                    ("unknown", "unknown"),
                )
            }
            for policy_id, _ in policies
        },
        "interpretation_limits": [
            (
                "Eligibility is URL-scope membership and does not "
                "prove relevance, correctness, safety, or action "
                "permission."
            ),
            (
                "A domain match is not evidence that two pages share "
                "a tenant or product catalog."
            ),
            (
                "Unknown PSL or IDNA cases are retained as unknown "
                "and excluded from eligible_references."
            ),
            (
                "The PSL is an exact locally retained snapshot; "
                "refreshes can change future results."
            ),
        ],
        "matrix_csv": matrix_path.name,
    }
    summary_path = destination / "scope-eligibility-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="repository worktree containing the retained source manifests",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help="private generated output directory",
    )
    args = parser.parse_args()
    result = run_scope_matrix(args.root, args.destination)
    print(
        json.dumps(
            {
                "actual_url_count": result["actual_url_count"],
                "pair_count": result["pair_count"],
                "matrix": str(args.destination / str(result["matrix_csv"])),
                "summary": str(args.destination / "scope-eligibility-summary.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    _main()

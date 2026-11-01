"""Focused checks for URL scope policy semantics and explicit unknowns."""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scopes import PINNED_IDNA_VERSION, ScopePolicy, SuffixList, evaluate_references


@pytest.fixture
def suffixes():
    return SuffixList.from_text(
        """
// ===BEGIN ICANN DOMAINS===
com
uk
co.uk
test
*.ck
!www.ck
// ===BEGIN PRIVATE DOMAINS===
blogspot.com
"""
    )


def _one(seed, reference, policy, *, suffixes=None):
    result = evaluate_references(seed, [reference], policy, suffixes=suffixes)
    assert len(result.decisions) == 1
    return result.decisions[0]


def test_exactpage_declares_query_and_fragment_behavior():
    seed = "https://example.com/item?id=1&variant=red#details"
    reference = "https://example.com/item?id=2&variant=red#other"

    included = _one(seed, reference, ScopePolicy("exactpage"))
    ignored = _one(
        seed,
        reference,
        ScopePolicy("exactpage", query_behavior="ignore"),
    )
    selected = _one(
        seed,
        reference,
        ScopePolicy("exactpage", query_behavior="keys", query_keys=("variant",)),
    )
    fragment_sensitive = _one(
        seed,
        reference,
        ScopePolicy("exactpage", fragment_behavior="include"),
    )

    assert included.eligible is False
    assert ignored.eligible is True
    assert selected.eligible is True
    assert fragment_sensitive.eligible is False


def test_exactpage_url_v1_normalizes_host_default_port_path_and_escapes():
    result = _one(
        "https://ExAMPLE.com:443/a/../%70roduct?sku=1#old",
        "https://example.com/product?sku=1#new",
        ScopePolicy("exactpage"),
    )

    assert result.eligible is True
    assert result.reason == "same_normalized_page"
    assert result.normalized_url == "https://example.com/product?sku=1#new"


def test_samehost_and_sameorigin_have_distinct_boundaries():
    seed = "http://example.com/item"
    reference = "https://example.com:443/other"

    assert _one(seed, reference, ScopePolicy("samehost")).eligible is True
    assert _one(seed, reference, ScopePolicy("sameorigin")).eligible is False


def test_registrable_domain_uses_full_co_uk_suffix(suffixes):
    policy = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=False,
        include_private_suffixes=False,
    )
    same = _one(
        "https://a.example.co.uk/item",
        "https://b.example.co.uk/other",
        policy,
        suffixes=suffixes,
    )
    different = _one(
        "https://a.example.co.uk/item",
        "https://b.other.co.uk/other",
        policy,
        suffixes=suffixes,
    )

    assert same.eligible is True
    assert different.eligible is False


def test_private_suffix_choice_changes_tenant_boundary(suffixes):
    shared_public_suffix = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=False,
        include_private_suffixes=False,
    )
    include_private = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=False,
        include_private_suffixes=True,
    )
    seed = "https://tenant-a.blogspot.com/item"
    reference = "https://tenant-b.blogspot.com/item"

    assert (
        _one(seed, reference, shared_public_suffix, suffixes=suffixes).eligible is True
    )
    assert _one(seed, reference, include_private, suffixes=suffixes).eligible is False


def test_registrable_domain_scheme_sensitivity_is_explicit(suffixes):
    sensitive = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=True,
        include_private_suffixes=False,
    )
    insensitive = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=False,
        include_private_suffixes=False,
    )
    seed = "http://example.com/item"
    reference = "https://shop.example.com/other"

    assert _one(seed, reference, sensitive, suffixes=suffixes).eligible is False
    assert _one(seed, reference, insensitive, suffixes=suffixes).eligible is True


def test_public_suffix_wildcard_and_exception_rules_are_applied(suffixes):
    policy = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=False,
        include_private_suffixes=False,
    )

    assert (
        _one(
            "https://x.a.foo.ck/item",
            "https://y.a.foo.ck/item",
            policy,
            suffixes=suffixes,
        ).eligible
        is True
    )
    assert (
        _one(
            "https://a.foo.ck/item", "https://b.bar.ck/item", policy, suffixes=suffixes
        ).eligible
        is False
    )
    assert (
        _one(
            "https://www.ck/item", "https://a.www.ck/item", policy, suffixes=suffixes
        ).eligible
        is True
    )


def test_suffix_lookalike_does_not_match_paypal_com(suffixes):
    policy = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=False,
        include_private_suffixes=False,
    )

    result = _one(
        "https://paypal.com/account",
        "https://paypal.com.evil.test/account",
        policy,
        suffixes=suffixes,
    )

    assert result.eligible is False
    assert result.reason == "different_registrable_domain"


def test_ip_localhost_and_unknown_suffixes_are_explicit_unknowns(suffixes):
    policy = ScopePolicy(
        "registrable-domain",
        scheme_sensitive=False,
        include_private_suffixes=False,
    )

    ip_result = _one(
        "https://192.0.2.1/item",
        "https://192.0.2.1/other",
        policy,
        suffixes=suffixes,
    )
    localhost_result = _one(
        "http://localhost/item",
        "http://localhost/other",
        policy,
        suffixes=suffixes,
    )
    unknown_suffix_result = _one(
        "https://a.internal/item",
        "https://b.internal/item",
        policy,
        suffixes=suffixes,
    )

    assert ip_result.eligible is None
    assert ip_result.reason == "seed_registrable_domain_unknown"
    assert localhost_result.eligible is None
    assert unknown_suffix_result.eligible is None


def test_invalid_urls_never_become_eligible():
    policy = ScopePolicy("samehost")
    invalid_port = _one(
        "https://example.com:99999/item",
        "https://example.com/item",
        policy,
    )
    invalid_reference = _one("https://example.com/item", "", policy)
    malformed_escape = _one(
        "https://example.com/item", "https://example.com/%ZZ", policy
    )
    empty_port = _one("https://example.com:/item", "https://example.com/item", policy)

    assert invalid_port.eligible is None
    assert invalid_port.reason.startswith("invalid_seed:")
    assert invalid_reference.eligible is None
    assert invalid_reference.reason == "invalid_reference:empty_or_non_string_url"
    assert malformed_escape.eligible is None
    assert malformed_escape.reason == "invalid_reference:invalid_percent_escape"
    assert empty_port.eligible is None
    assert empty_port.reason == "invalid_seed:empty_port"


def test_invalid_registrable_policy_choices_are_rejected():
    with pytest.raises(ValueError, match="explicit scheme_sensitive"):
        ScopePolicy("registrable-domain", include_private_suffixes=False)
    with pytest.raises(ValueError, match="explicit include_private_suffixes"):
        ScopePolicy("registrable-domain", scheme_sensitive=False)


def test_idna_host_is_checked_or_reports_unavailable_support():
    result = _one(
        "https://bücher.example/item",
        "https://xn--bcher-kva.example/item",
        ScopePolicy("samehost"),
    )

    if importlib.util.find_spec("idna") is None:
        assert result.eligible is None
        assert result.reason == "invalid_seed:idna_support_unavailable"
    else:
        import idna

        if idna.__version__ == PINNED_IDNA_VERSION:
            assert result.eligible is True
        else:
            assert result.eligible is None
            assert result.reason == "invalid_seed:idna_version_not_pinned"


def test_pinned_idna_preserves_sharp_s_and_accepts_a_label_equivalence():
    policy = ScopePolicy("samehost")
    equivalent = _one(
        "https://bücher.example/item",
        "https://xn--bcher-kva.example/item",
        policy,
    )
    sharp_s = _one("https://faß.de/item", "https://fass.de/item", policy)

    assert equivalent.eligible is True
    assert sharp_s.eligible is False


def test_pinned_idna_rejects_invalid_dns_and_a_labels():
    policy = ScopePolicy("samehost")
    invalid_ascii = _one(
        "https://example.com/item", "https://-bad.example/item", policy
    )
    invalid_alabel = _one(
        "https://example.com/item", "https://xn--.example/item", policy
    )

    assert invalid_ascii.eligible is None
    assert invalid_ascii.reason.startswith("invalid_reference:invalid_idna_host:")
    assert invalid_alabel.eligible is None
    assert invalid_alabel.reason.startswith("invalid_reference:invalid_idna_host:")


def test_unrestricted_still_rejects_invalid_urls():
    result = _one(
        "file:///tmp/item", "https://example.com/item", ScopePolicy("unrestricted")
    )
    assert result.eligible is None
    assert result.reason == "invalid_seed:unsupported_scheme"

"""The `net2` schema and the normalization helpers that feed it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.observations import anchoring
from yosoi.observations.models import network as network_models
from yosoi.observations.models.network import (
    NetworkCapability,
    NetworkCapabilityKind,
    NetworkRedaction,
    NetworkRequest,
    NetworkTrace,
    QueryParam,
    ResourceType,
    RestrictedBody,
    ShapeSignature,
    TimingBucket,
    ValueClass,
    duplicate_key,
    parse_network_trace,
    serialize_network_trace,
    shape_digest,
)
from yosoi.observations.network_tree import (
    SENSITIVE_HEADER_SUBSTRINGS,
    classify_params,
    classify_value,
    credential_header_names,
    json_key_skeleton,
    normalize_url,
    path_template,
    shape_signature,
    timing_bucket,
)

DIGEST = 'a' * 64


def _request(**overrides) -> NetworkRequest:
    """Build a valid request, letting a test override exactly one thing."""
    fields = {
        'request_id': 'r1',
        'method': 'GET',
        'origin': 'https://api.example',
        'path_template': '/v1/things/{id}',
        'params': (),
        'status': 200,
        'resource_type': ResourceType.XHR,
        'mime': 'application/json',
    }
    fields.update(overrides)
    fields.setdefault(
        'duplicate_key',
        duplicate_key(fields['method'], fields['origin'], fields['path_template'], tuple(fields['params'])),
    )
    return NetworkRequest(**fields)


# ── Classification is closed and total ────────────────────────────────────────


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('', ValueClass.EMPTY),
        ('2026-08-08', ValueClass.TIMESTAMP),
        ('2026-08-08T12:30:00Z', ValueClass.TIMESTAMP),
        ('1735689600', ValueClass.TIMESTAMP),
        ('1735689600000', ValueClass.TIMESTAMP),
        ('4105', ValueClass.ID),
        ('3f9c2b1d', ValueClass.ID),
        ('123e4567-e89b-12d3-a456-426614174000', ValueClass.ID),
        ('abc123abc123abc123abc', ValueClass.TOKEN),
        ('newest-first', ValueClass.ENUM),
        ('a value with spaces', ValueClass.OPAQUE),
    ],
)
def test_every_value_lands_in_exactly_one_declared_class(value: str, expected: ValueClass) -> None:
    assert classify_value(value) is expected


def test_overlapping_classes_resolve_by_the_declared_order() -> None:
    # Ten digits is both an epoch second and an integer id; the order decides, always.
    assert classify_value('1735689600') is ValueClass.TIMESTAMP
    assert classify_value('173568960') is ValueClass.ID
    # A twenty-character lowercase hex string is both a hex id and token-shaped; id wins.
    assert classify_value('a' * 19 + '1') is ValueClass.ID
    # An ODD-length hex string is not a byte sequence, so it falls through to token. Asserted
    # rather than tidied away: the byte-pair rule is what makes a hex id recognizable at all.
    assert classify_value('a' * 20 + '1') is ValueClass.TOKEN


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        ('/v1/products/4105', '/v1/products/{id}'),
        ('/static/3f9c2b1d.js', '/static/{id}.js'),
        ('/img/00001139.png', '/img/{id}.png'),
        ('/v1/orders/2026-08-08', '/v1/orders/{timestamp}'),
        ('/v1/checkout/quote', '/v1/checkout/quote'),
        ('/shipping-zones', '/shipping-zones'),
        ('/', '/'),
    ],
)
def test_path_templating_replaces_only_value_shaped_segments(path: str, expected: str) -> None:
    assert path_template(path) == expected


def test_templating_uses_no_frequency_threshold() -> None:
    """One occurrence and a thousand produce the same template — there is no knob."""
    assert path_template('/v1/products/1') == path_template('/v1/products/999999') == '/v1/products/{id}'
    # And a literal directory never becomes a placeholder because many files live under it.
    assert path_template('/static/a.js').startswith('/static/')


def test_normalizing_a_url_keeps_no_value() -> None:
    origin, template, params = normalize_url('https://API.Example:8443/v1/orders/4105?sort=newest&t=1735689600#frag')

    assert origin == 'https://api.example:8443'
    assert template == '/v1/orders/{id}'
    assert params == (
        QueryParam(name='sort', value_class=ValueClass.ENUM),
        QueryParam(name='t', value_class=ValueClass.TIMESTAMP),
    )
    assert all('newest' not in repr(param) for param in params)


def test_normalizing_a_url_strips_userinfo_and_canonicalizes_its_authority() -> None:
    origin, template, _ = normalize_url('HTTPS://user:password@BÜCHER.example.:443/v1/items/%31%32%33')

    assert origin == 'https://xn--bcher-kva.example'
    assert template == '/v1/items/{id}'
    assert 'user' not in origin
    assert 'password' not in origin


@pytest.mark.parametrize(
    'secret',
    [
        'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature',
        'c2Vzc2lvbi10b2tlbi13aXRoLXNlY3JldA==',
        '%65%79%4A%68%62%47%63%69%4F%69%4A%49%55%7A%49%31%4E%69%4A%39',
    ],
)
def test_token_shaped_path_values_are_never_retained(secret: str) -> None:
    _, template, _ = normalize_url(f'https://api.example/v1/session/{secret}')

    assert secret not in template
    assert template == '/v1/session/{token}'


def test_equivalent_query_order_and_default_ports_canonicalize_identically() -> None:
    first = normalize_url('https://EXAMPLE.com:443/v1/items?z=1&a=newest')
    second = normalize_url('https://example.com/v1/items?a=newest&z=1')

    assert first == second


def test_a_repeated_parameter_name_keeps_one_class() -> None:
    assert classify_params('id=1&id=abc') == (QueryParam(name='id', value_class=ValueClass.ID),)


def test_a_url_without_an_origin_is_refused() -> None:
    with pytest.raises(ValueError, match='no origin'):
        normalize_url('/v1/relative')


@pytest.mark.parametrize(
    ('duration', 'expected'),
    [
        (None, 'unknown'),
        (-1, 'unknown'),
        (0, 'instant'),
        (49.9, 'instant'),
        (50, 'fast'),
        (999, 'moderate'),
        (2_999, 'slow'),
        (3_000, 'very_slow'),
    ],
)
def test_timing_buckets_use_schema_fixed_boundaries(duration: float | None, expected: str) -> None:
    assert timing_bucket(duration) == expected
    assert TimingBucket(expected)


# ── Shape is keys, never content ──────────────────────────────────────────────


def test_a_key_skeleton_carries_no_values() -> None:
    keys = json_key_skeleton({'items': [{'sku': 'SECRET-SKU', 'qty': 3}], 'total': '9.99'})

    assert keys == ('items', 'items[]', 'items[].qty', 'items[].sku', 'total')
    assert all('SECRET' not in key and '9.99' not in key for key in keys)


def test_cardinality_does_not_change_a_shape() -> None:
    one = shape_signature({'items': [{'sku': 'a'}]})
    many = shape_signature({'items': [{'sku': 'a'}, {'sku': 'b'}, {'sku': 'c'}]})

    assert one.digest == many.digest


def test_a_missing_key_does_change_a_shape() -> None:
    assert shape_signature({'total': 1}).digest != shape_signature({'total': 1, 'items': []}).digest


def test_shape_drift_after_the_retained_key_prefix_changes_the_digest() -> None:
    baseline = {f'field_{index:03}': index for index in range(70)}
    drifted = baseline | {'field_069': 0, 'tail_only_change': True}

    first = shape_signature(baseline)
    second = shape_signature(drifted)

    assert first.truncated
    assert second.truncated
    assert first.keys == second.keys
    assert first.digest != second.digest


def test_a_truncated_shape_cannot_claim_only_its_visible_prefix_digest() -> None:
    keys = tuple(f'field_{index:03}' for index in range(64))

    with pytest.raises(ValidationError, match='omitted key skeleton'):
        ShapeSignature(digest=shape_digest(keys), keys=keys, truncated=True)


def test_a_shape_signature_cannot_disagree_with_its_own_keys() -> None:
    with pytest.raises(ValidationError, match='disagrees with its own key skeleton'):
        ShapeSignature(digest=shape_digest(('a',)), keys=('b',))


# ── The schema refuses to hold a secret ───────────────────────────────────────


def test_a_query_parameter_has_no_slot_for_a_value() -> None:
    assert 'value' not in QueryParam.model_fields
    with pytest.raises(ValidationError):
        QueryParam(name='token', value_class=ValueClass.TOKEN, value='anything')


@pytest.mark.parametrize('name', ['authorization: Bearer x', 'Authorization', 'x auth', 'set cookie'])
def test_a_header_name_slot_rejects_anything_that_is_not_a_field_name(name: str) -> None:
    with pytest.raises(ValidationError, match='lowercased HTTP field name'):
        _request(request_header_names=(name,))


def test_header_names_are_kept_because_a_name_is_evidence() -> None:
    request = _request(request_header_names=('accept', 'authorization', 'x-csrf-token'))

    assert credential_header_names(request.request_header_names) == ('authorization', 'x-csrf-token')


def test_a_manually_constructed_origin_cannot_carry_userinfo() -> None:
    with pytest.raises(ValidationError, match='userinfo'):
        _request(origin='https://user:password@api.example')


def test_the_credential_name_list_is_the_one_voidcrawl_uses() -> None:
    """Inherited, not invented: two lists would eventually disagree about what a credential is."""
    for name in ('authorization', 'proxy-authorization', 'cookie', 'x-api-key', 'x-amz-security-token', 'x-password'):
        assert credential_header_names((name,)) == (name,)
    for name in ('content-type', 'accept', 'etag', 'location', 'referer'):
        assert credential_header_names((name,)) == ()
    assert 'authorization' in SENSITIVE_HEADER_SUBSTRINGS


def test_the_redaction_record_cannot_describe_an_unredacted_trace() -> None:
    with pytest.raises(ValidationError):
        NetworkRedaction(header_values='kept')
    with pytest.raises(ValidationError):
        NetworkRedaction(param_values='verbatim')


def test_a_retained_body_must_be_declared_and_is_never_inlined() -> None:
    body = RestrictedBody(artifact_sha256=DIGEST, media_type='application/json', size_bytes=12)
    assert 'content' not in RestrictedBody.model_fields

    with pytest.raises(ValidationError, match='retained bodies while the trace declares bodies dropped'):
        NetworkTrace(snapshot_id='s', requests=(_request(restricted_body=body),))

    trace = NetworkTrace(
        snapshot_id='s',
        requests=(_request(restricted_body=body),),
        redaction=NetworkRedaction(bodies='restricted_artifact'),
    )
    assert trace.requests[0].restricted_body == body


# ── Integrity ─────────────────────────────────────────────────────────────────


def test_a_duplicate_key_cannot_disagree_with_the_call_it_groups() -> None:
    with pytest.raises(ValidationError, match='disagrees with the call signature'):
        NetworkRequest(
            request_id='r',
            method='GET',
            origin='https://api.example',
            path_template='/v1/x',
            duplicate_key='0' * 16,
        )


def test_two_calls_differing_only_in_an_id_share_a_duplicate_key() -> None:
    shared = duplicate_key('GET', 'https://api.example', '/v1/products/{id}', ())
    other = duplicate_key(
        'GET', 'https://api.example', '/v1/products/{id}', (QueryParam(name='q', value_class=ValueClass.ENUM),)
    )

    assert shared != other
    assert duplicate_key('POST', 'https://api.example', '/v1/products/{id}', ()) != shared


@pytest.mark.parametrize(
    ('field', 'value', 'match'),
    [
        ('origin', 'https://api.example/v1', 'scheme and authority'),
        ('origin', 'api.example', 'scheme and authority'),
        ('path_template', 'v1/x', 'must start with a slash'),
        ('path_template', '/v1/x?a=b', 'carries no query string'),
        ('path_template', '/v1/x#frag', 'cannot be expressed in an address'),
        ('method', 'get', None),
        ('status', 99, None),
    ],
)
def test_malformed_requests_fail_closed(field: str, value: object, match: str | None) -> None:
    with pytest.raises(ValidationError, match=match):
        _request(**{field: value})


def test_an_older_network_schema_is_refused_instead_of_reinterpreted() -> None:
    with pytest.raises(ValidationError, match="expected 'net2'"):
        NetworkTrace(schema_version='net1', snapshot_id='s')


def test_a_trace_refuses_duplicate_request_ids_and_repeated_capabilities() -> None:
    with pytest.raises(ValidationError, match='request ids must be unique'):
        NetworkTrace(snapshot_id='s', requests=(_request(), _request()))
    with pytest.raises(ValidationError, match='at most one entry per kind'):
        NetworkTrace(
            snapshot_id='s',
            capabilities=(
                NetworkCapability(kind=NetworkCapabilityKind.SIZES, available=True),
                NetworkCapability(kind=NetworkCapabilityKind.SIZES, available=False, reason='x'),
            ),
        )


def test_an_unavailable_capability_must_state_a_reason() -> None:
    with pytest.raises(ValidationError, match='must state a reason'):
        NetworkCapability(kind=NetworkCapabilityKind.TIMINGS, available=False)


def test_completeness_is_declared_and_never_assumed() -> None:
    assert not NetworkTrace(snapshot_id='s').complete
    declared = NetworkTrace(
        snapshot_id='s',
        capabilities=(NetworkCapability(kind=NetworkCapabilityKind.COMPLETE_TRACE, available=True),),
    )
    assert declared.complete


def test_the_reserved_character_rule_is_the_shared_one() -> None:
    assert tuple(network_models._LOCATOR_RESERVED) == tuple(anchoring.LOCATOR_RESERVED)


def test_serialization_round_trips_deterministically() -> None:
    trace = NetworkTrace(snapshot_id='s', requests=(_request(response_shape=shape_signature({'a': 1})),))

    data = serialize_network_trace(trace)
    assert data == serialize_network_trace(parse_network_trace(data))
    assert parse_network_trace(data) == trace


def test_a_foreign_field_is_refused_rather_than_carried() -> None:
    with pytest.raises(ValidationError):
        _request(cookie_jar='anything')

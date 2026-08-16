"""The seeded 400-request network trace `boss_fights.md` specifies, generated deterministically.

```text
400 requests
├── 250 assets
├──  80 analytics/ad/telemetry
├──  40 duplicate API calls
├──  20 irrelevant JSON calls
├──   8 useful API calls
└──   2 requests containing the actual defect
```

Two things about this fixture are deliberate and load-bearing:

* **The defects hide INSIDE groups, not beside them.** A 500 sitting on its own endpoint would be
  found by any reducer that lists endpoints. Defect A is the sixth call to an endpoint whose other
  five succeeded; defect B is the forty-first poll of an endpoint whose other forty returned the
  same shape. Finding them requires noticing that a member deviates from its own group, which is
  the only thing the ranking is allowed to notice.
* **There are no credentials, and none of the shapes that imply one.** No bearer values, no session
  cookies, no `?access_token=`, and no `token`-class values anywhere — not even fake ones, because a
  fixture that carries plausible-looking secrets teaches a reader to expect them here. Header NAMES
  are present, including `authorization`, because a name is evidence and the schema has nowhere to
  put a value.

Pure function of its arguments: same snapshot id, byte-identical output, no clock, no randomness.
"""

from __future__ import annotations

from yosoi.observations.models.network import (
    InitiatorKind,
    NetworkCapability,
    NetworkCapabilityKind,
    NetworkRequest,
    NetworkTrace,
    ResourceType,
    ShapeSignature,
    TimingBucket,
    duplicate_key,
    serialize_network_trace,
)
from yosoi.observations.network_tree import normalize_url, shape_signature

SNAPSHOT_ID = 'network_seeded_400'

DEFECT_STATUS_ID = 'req_defect_status'
DEFECT_SHAPE_ID = 'req_defect_shape'

_CDN = 'https://cdn.shop.example'
_API = 'https://api.shop.example'

_JSON = 'application/json'
_PROBLEM_JSON = 'application/problem+json'

_API_REQUEST_HEADERS = ('accept', 'authorization')
"""Header NAMES an authenticated JSON endpoint requires. No values exist to carry."""

_RESPONSE_HEADERS = ('content-length', 'content-type', 'date')

_CART_PAYLOAD = {
    'items': [{'sku': 'a', 'qty': 1}, {'sku': 'b', 'qty': 1}, {'sku': 'c', 'qty': 1}],
    'total': '0.00',
    'currency': 'EUR',
}
_CART_DRIFT_PAYLOAD = {'total': '0.00', 'currency': 'EUR'}
_PRODUCT_PAYLOAD = {'id': 0, 'title': 'x', 'price': '0.00', 'stock': 0}
_PROBLEM_PAYLOAD = {'type': 'about:blank', 'title': 'x', 'status': 500, 'detail': 'x'}
_CONFIG_PAYLOAD = {'enabled': True, 'label': 'x'}

_ASSETS = (
    (60, '/static/{:08x}.js', ResourceType.SCRIPT, 'application/javascript'),
    (30, '/static/{:08x}.css', ResourceType.STYLESHEET, 'text/css'),
    (120, '/img/{:08x}.png', ResourceType.IMAGE, 'image/png'),
    (20, '/img/{:08x}.svg', ResourceType.IMAGE, 'image/svg+xml'),
    (20, '/fonts/{:08x}.woff2', ResourceType.FONT, 'font/woff2'),
)

_IRRELEVANT = (
    'config',
    'banners',
    'flags',
    'geo',
    'locales',
    'currencies',
    'shipping-zones',
    'payment-methods',
    'store-hours',
    'legal-links',
    'social-links',
    'newsletter-copy',
    'seo-meta',
    'menu-tree',
    'promo-strip',
    'reviews-summary',
    'faq-blocks',
    'trust-badges',
    'footer-copy',
    'cookie-copy',
)


def _request(
    request_id: str,
    method: str,
    url: str,
    *,
    status: int,
    resource_type: ResourceType,
    mime: str,
    timing: TimingBucket,
    initiator: InitiatorKind,
    request_headers: tuple[str, ...] = (),
    response_shape: ShapeSignature | None = None,
    request_bytes: int = 0,
    response_bytes: int = 0,
    declared_item_count: int | None = None,
) -> NetworkRequest:
    """Build one already-normalized request; the raw URL never survives this call."""
    origin, template, params = normalize_url(url)
    return NetworkRequest(
        request_id=request_id,
        method=method,
        origin=origin,
        path_template=template,
        params=params,
        status=status,
        resource_type=resource_type,
        mime=mime,
        timing=timing,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        initiator=initiator,
        response_shape=response_shape,
        request_header_names=request_headers,
        response_header_names=_RESPONSE_HEADERS,
        declared_item_count=declared_item_count,
        duplicate_key=duplicate_key(method, origin, template, params),
    )


def _assets() -> list[NetworkRequest]:
    """250 static assets: the volume every important request has to survive."""
    out: list[NetworkRequest] = []
    for count, pattern, resource_type, mime in _ASSETS:
        for _ in range(count):
            serial = len(out) + 1
            out.append(
                _request(
                    f'req_asset_{serial:04d}',
                    'GET',
                    f'{_CDN}{pattern.format(0x1000 + serial)}',
                    status=200,
                    resource_type=resource_type,
                    mime=mime,
                    timing=TimingBucket.FAST,
                    initiator=InitiatorKind.PARSER,
                    response_bytes=4_096,
                )
            )
    return out


def _analytics() -> list[NetworkRequest]:
    """80 telemetry calls: high volume, uninteresting, and never named by a host allowlist."""
    beacons = [
        _request(
            f'req_metrics_{index:04d}',
            'POST',
            f'https://metrics.example/collect?t=173568960{index:04d}&n={0xA0 + index:08x}',
            status=204,
            resource_type=ResourceType.BEACON,
            mime='text/plain',
            timing=TimingBucket.FAST,
            initiator=InitiatorKind.SCRIPT,
            request_bytes=512,
        )
        for index in range(40)
    ]
    pixels = [
        _request(
            f'req_pixel_{index:04d}',
            'GET',
            f'https://ads.example/pixel/{0xB0 + index:08x}.gif',
            status=200,
            resource_type=ResourceType.IMAGE,
            mime='image/gif',
            timing=TimingBucket.INSTANT,
            initiator=InitiatorKind.SCRIPT,
            response_bytes=43,
        )
        for index in range(25)
    ]
    events = [
        _request(
            f'req_telemetry_{index:04d}',
            'POST',
            'https://t.example/e',
            status=202,
            resource_type=ResourceType.BEACON,
            mime='text/plain',
            timing=TimingBucket.FAST,
            initiator=InitiatorKind.SCRIPT,
            request_bytes=256,
        )
        for index in range(15)
    ]
    return [*beacons, *pixels, *events]


def _duplicate_api() -> list[NetworkRequest]:
    """40 identical cart polls: one region and one count, not forty lines."""
    shape = shape_signature(_CART_PAYLOAD)
    return [
        _request(
            f'req_cart_{index:04d}',
            'GET',
            f'{_API}/v1/cart',
            status=200,
            resource_type=ResourceType.XHR,
            mime=_JSON,
            timing=TimingBucket.FAST,
            initiator=InitiatorKind.SCRIPT,
            request_headers=_API_REQUEST_HEADERS,
            response_shape=shape,
            response_bytes=310,
            declared_item_count=3,
        )
        for index in range(40)
    ]


def _irrelevant_json() -> list[NetworkRequest]:
    """20 one-off JSON calls, each on its own template: the singleton decoys."""
    shape = shape_signature(_CONFIG_PAYLOAD)
    return [
        _request(
            f'req_misc_{index:04d}',
            'GET',
            f'{_API}/v1/{name}',
            status=200,
            resource_type=ResourceType.XHR,
            mime=_JSON,
            timing=TimingBucket.FAST,
            initiator=InitiatorKind.SCRIPT,
            request_headers=_API_REQUEST_HEADERS,
            response_shape=shape,
            response_bytes=120,
        )
        for index, name in enumerate(_IRRELEVANT)
    ]


def _useful_api() -> list[NetworkRequest]:
    """8 calls that carry the page's actual data — five of them one repeated endpoint."""
    product = shape_signature(_PRODUCT_PAYLOAD)
    out = [
        _request(
            f'req_product_{index:04d}',
            'GET',
            f'{_API}/v1/products/{4100 + index}',
            status=200,
            resource_type=ResourceType.XHR,
            mime=_JSON,
            timing=TimingBucket.FAST,
            initiator=InitiatorKind.SCRIPT,
            request_headers=_API_REQUEST_HEADERS,
            response_shape=product,
            response_bytes=240,
        )
        for index in range(5)
    ]
    for name, path in (('quote', '/v1/checkout/quote'), ('preferences', '/v1/user/preferences')):
        out.append(
            _request(
                f'req_{name}',
                'GET',
                f'{_API}{path}',
                status=200,
                resource_type=ResourceType.XHR,
                mime=_JSON,
                timing=TimingBucket.MODERATE,
                initiator=InitiatorKind.SCRIPT,
                request_headers=_API_REQUEST_HEADERS,
                response_shape=shape_signature(_CONFIG_PAYLOAD),
                response_bytes=180,
            )
        )
    out.append(
        _request(
            'req_inventory',
            'GET',
            f'{_API}/v1/inventory/9902',
            status=200,
            resource_type=ResourceType.XHR,
            mime=_JSON,
            timing=TimingBucket.FAST,
            initiator=InitiatorKind.SCRIPT,
            request_headers=_API_REQUEST_HEADERS,
            response_shape=shape_signature(_CONFIG_PAYLOAD),
            response_bytes=90,
        )
    )
    return out


def _defects() -> list[NetworkRequest]:
    """The two requests the reader is supposed to find without being told to look."""
    return [
        # A sixth call to an endpoint whose other five returned 200 and a product record.
        _request(
            DEFECT_STATUS_ID,
            'GET',
            f'{_API}/v1/products/4105',
            status=500,
            resource_type=ResourceType.XHR,
            mime=_PROBLEM_JSON,
            timing=TimingBucket.SLOW,
            initiator=InitiatorKind.SCRIPT,
            request_headers=_API_REQUEST_HEADERS,
            response_shape=shape_signature(_PROBLEM_PAYLOAD),
            response_bytes=150,
        ),
        # A forty-first cart poll that succeeded and quietly stopped returning the line items.
        _request(
            DEFECT_SHAPE_ID,
            'GET',
            f'{_API}/v1/cart',
            status=200,
            resource_type=ResourceType.XHR,
            mime=_JSON,
            timing=TimingBucket.FAST,
            initiator=InitiatorKind.SCRIPT,
            request_headers=_API_REQUEST_HEADERS,
            response_shape=shape_signature(_CART_DRIFT_PAYLOAD),
            response_bytes=48,
            declared_item_count=0,
        ),
    ]


_CAPABILITIES = (
    NetworkCapability(kind=NetworkCapabilityKind.COMPLETE_TRACE, available=True),
    NetworkCapability(kind=NetworkCapabilityKind.TIMINGS, available=True),
    NetworkCapability(kind=NetworkCapabilityKind.SIZES, available=True),
    NetworkCapability(kind=NetworkCapabilityKind.INITIATORS, available=True),
    NetworkCapability(kind=NetworkCapabilityKind.RESPONSE_SHAPES, available=True),
    NetworkCapability(kind=NetworkCapabilityKind.HEADER_NAMES, available=True),
    NetworkCapability(kind=NetworkCapabilityKind.ITEM_COUNTS, available=True),
    NetworkCapability(
        kind=NetworkCapabilityKind.REQUEST_SHAPES,
        available=False,
        reason='the telemetry beacons post opaque payloads, dropped before canonicalization',
    ),
)


def build_network_trace(snapshot_id: str = SNAPSHOT_ID) -> NetworkTrace:
    """Return the seeded trace as a validated model, in the order the page made the calls."""
    requests = [
        *_assets(),
        *_analytics(),
        *_duplicate_api(),
        *_irrelevant_json(),
        *_useful_api(),
        *_defects(),
    ]
    return NetworkTrace(snapshot_id=snapshot_id, requests=tuple(requests), capabilities=_CAPABILITIES)


def render_network_trace(snapshot_id: str = SNAPSHOT_ID) -> bytes:
    """Return the canonical bytes of the seeded 400-request trace."""
    return serialize_network_trace(build_network_trace(snapshot_id))


__all__ = ['DEFECT_SHAPE_ID', 'DEFECT_STATUS_ID', 'SNAPSHOT_ID', 'build_network_trace', 'render_network_trace']

# Deterministic extractor fields

`ys.Extractor()` declares a contract field whose value is computed asynchronously from each already-acquired row. It is intended for traditional scraper logic such as links, attributes, JSON-LD, and normalized contact metadata that does not need selector discovery.

```python
import yosoi as ys
from pydantic import BaseModel


class SocialProfile(BaseModel):
    platform: str
    url: str

    @classmethod
    def from_url(cls, url: str):
        if 'linkedin.com/' in url:
            return cls(platform='linkedin', url=url)
        return None


class Company(ys.Contract):
    # No root means the complete document is one Company row.
    name: str = ys.css('h1').text()
    socials: list[SocialProfile] = (
        ys.css('a[href]').attr('href').map(SocialProfile.from_url).compact()
    )
```

The annotation is the runtime value type. `ys.Extractor()` is Pydantic `FieldInfo` metadata and never becomes the model value.

## Invariants

- Extractors are async-capable and deterministic; Yosoi awaits each field in declaration order.
- An extractor receives only already-acquired evidence. It has no fetcher, browser, model, or network handle.
- Extractors never invoke selector discovery or an LLM.
- Extraction happens once per contract row.
- A contract without a root treats the whole page as one row.
- An explicit root runs the extractor independently inside every matched container.
- Values are validated against the complete field annotation before acceptance.
- A required field fails closed. An optional/defaulted field uses its declared default on `ExtractorNoMatch` or validation failure.
- Extractor values are not stored in selector caches or fingerprint references.

Root discovery remains a separate pipeline operation. A contract with `root = ys.discover()` may require a model to discover the row boundary even though its extractor fields do not use one.

## Supplying extraction logic

Yosoi resolves exactly one strategy per field. Multiple explicit strategies fail at contract-definition time.

### 1. Fluent CSS/XPath plans

`ys.css()` and `ys.xpath()` remain bare root selectors until a terminal operation creates extractor field metadata:

```python
class Company(ys.Contract):
    name: str = ys.css('h1').text()
    links: list[str] = ys.xpath('//a[@href]').attr('href')
```

The field annotation supplies the cardinality and output type: scalar fields select the first match; collection fields keep every match. A collection query with no matches returns an empty collection value, so it does not need `default_factory=list`.

`.map(importable_callable)` applies deterministic Python to each selected value and may be chained. `.compact()` removes `None` results. Plans are serialized into contract specs and recipes. Stored plan strategies are not currently eligible for fingerprint-generalized execution.

### 2. Field-bound decorator

Bind arbitrary Python directly to a marker without `@staticmethod` or an `extract_<field>` naming convention:

```python
class Company(ys.Contract):
    industry: str = ys.Extractor()

    @ys.extraction(industry)
    async def industry_from_meta(row: ys.ExtractionRow) -> str:
        values = row.attribute('meta[name="industry"]', 'content')
        if not values:
            raise ys.ExtractorNoMatch()
        return values[0]
```

### 3. Multi-field callback

A batch callback executes once per row. Callback errors are atomic; returned values are validated and fingerprinted independently for each target field:

```python
class Company(ys.Contract):
    phone: str = ys.Extractor()
    emails: list[str] = ys.Extractor()

    @ys.extractions(phone, emails)
    async def contacts(row: ys.ExtractionRow):
        links = row.attribute('a[href]', 'href')
        return ys.values(
            phone=next(value for value in links if value.startswith('tel:')),
            emails=[value for value in links if value.startswith('mailto:')],
        )
```

### 4. Explicit callable

```python
async def links(row: ys.ExtractionRow) -> list[str]:
    return row.attribute('a[href]', 'href')


class Company(ys.Contract):
    links: list[str] = ys.Extractor(using=links, version='2')
```

Portable callables must be importable module-level functions or methods. A process-local closure or lambda requires both `key=` and `version=` and cannot be rendered into a portable recipe.

### 5. Legacy contract field method

```python
class Company(ys.Contract):
    emails: list[str] = ys.Extractor()

    @staticmethod
    async def extract_emails(row: ys.ExtractionRow) -> list[str]:
        return [value.removeprefix('mailto:') for value in row.attribute('a[href]', 'href') if value.startswith('mailto:')]
```

The method name is `extract_<field_name>` and it accepts exactly one positional `ExtractionRow`.

### 6. Annotated output-type hook

```python
class SocialProfile(BaseModel):
    platform: str
    url: str

    @classmethod
    async def __yosoi_extract__(cls, row: ys.ExtractionRow) -> list['SocialProfile']:
        return [cls(platform='x', url=url) for url in row.attribute('a[href]', 'href') if 'x.com/' in url]


class Company(ys.Contract):
    socials: list[SocialProfile] = ys.Extractor()
```

For `list[T]`, Yosoi calls `T.__yosoi_extract__` once for the row and validates the returned iterable as `list[T]`.

### 7. Exact registry entry

```python
@ys.register_extractor(list[SocialProfile], key='company.socials', version='1')
async def social_profiles(row: ys.ExtractionRow) -> list[SocialProfile]:
    ...
```

Registry dispatch uses the complete normalized annotation or an exact Yosoi semantic type. It does not search for approximately compatible extractors. Conflicting exact registrations fail closed.

## `ExtractionRow`

The row context is read-only and scoped to one record:

| API | Result | Fingerprint evidence |
| --- | --- | --- |
| `row.url`, `row.index`, `row.root_scope` | Acquisition/row metadata | Values are not copied into evidence |
| `row.config` | Frozen JSON-compatible `Extractor(config=...)` mapping | Configuration belongs to strategy identity |
| `row.css(query)` | Parsel selector list | DOM operation and hashed target |
| `row.xpath(query)` | Parsel selector list | DOM operation and hashed target |
| `row.attribute(query, name, xpath=False)` | Attribute values | Attribute operation; values excluded |
| `row.text(query=None, xpath=False, all=False)` | Normalized text | Text operation; text excluded |
| `row.json_ld(path=None)` | JSON-LD payloads/path values | JSON-LD operation; values excluded |
| `row.json_ld_mappings()` | Recursive JSON-LD mappings | JSON-LD traversal |
| `row.runtime_values(channel=None)` | Values already observed during acquisition | Channel operation; values excluded |
| `row.raw_html` / `row.html` | Raw row HTML | Marks the strategy opaque unless structured evidence is also emitted |

Runtime evidence is application-defined and pre-fetched:

```python
records = await ys.extract(
    html,
    Company,
    url='https://example.com/',
    runtime_evidence={
        'resource_urls': captured_resource_urls,
        'endpoints': captured_endpoints,
    },
)
```

## Outcomes and failures

Raise `ys.ExtractorNoMatch` for an expected absence:

```python
async def primary_phone(row: ys.ExtractionRow) -> str:
    values = [value for value in row.attribute('a[href]', 'href') if value.startswith('tel:')]
    if not values:
        raise ys.ExtractorNoMatch()
    return values[0].removeprefix('tel:')
```

- Required field: raises `ExtractorFieldError` with row, field, resolver, and content-free category.
- Defaulted field: uses `default` or `default_factory`.
- Invalid output: fails field annotation validation and never returns the raw value.
- Coroutine functions are awaited; async generators are rejected because each field must produce one final value.
- Programming errors: propagate rather than falling back to another strategy or an LLM.

`ExtractionOutcome(value, evidence=...)` may attach explicit `ExtractionEvidence`. Prefer instrumented row helpers so evidence targets are hashed consistently.

## Pre-fetched extraction

`ys.extract` runs asynchronously without acquisition, browser actions, selector discovery, or model setup and returns validated dictionaries:

```python
records = await ys.extract(page_html, Company, url='https://example.com/company/1')
```

`ys.extract(...)` is always async and must be awaited; there is no separate async shim or synchronous wrapper.

Mixed contracts must supply selectors for required selector-backed fields. A discovered root must be supplied explicitly with `root=`. `ys.extract` rejects `ys.js()` and `ys.File()` fields because it does not own a browser or downloader.

Unlike selector discovery, deterministic/cache-only execution does not require an API key. If a normal scrape later reaches discovery without a configured model, it still fails closed at that boundary.

## Fingerprints and generalized strategy reuse

Every successful extractor execution emits an in-memory `ExtractorFingerprint` containing:

- content-free page and row structure;
- route template and root scope;
- field/output identity;
- resolver ID and version;
- hashed operation targets and evidence source kinds;
- validation result and cardinality band.

It does **not** contain extracted values, raw HTML, visible text, attribute values, URL queries, emails, phone numbers, or social profile URLs. Fingerprints describe how evidence was found, not what was found.

Persistence and reuse are default-deny:

```python
from yosoi.fingerprints import FingerprintStore

store = FingerprintStore('.yosoi/fingerprint')
observe = ys.Policy(
    extractor=ys.ExtractorPolicy(reference_writes=True),
)
reuse = ys.Policy(
    trust_tier='yellow',
    extractor=ys.ExtractorPolicy(
        generalized_reads=True,
        allowed_references=('myapp.extractors:links',),
    ),
)

await ys.extract(html, KnownCompany, policy=observe, fingerprint_store=store)
records = await ys.extract(next_html, AutoCompany, policy=reuse, fingerprint_store=store)
```

For `ys.scrape`, Yosoi uses the default `.yosoi/fingerprint/` store when the extractor policy enables reference I/O. Pure `ys.extract` and `resolve` require an explicit store so hidden filesystem state cannot affect replay.

A fingerprint-proposed strategy runs only when all of these hold:

1. `generalized_reads=True`;
2. `trust_tier='yellow'` allows the quarantined `fingerprint` source;
3. the exact stored `module:qualname` appears in `allowed_references`;
4. field name, semantic type, output annotation, route, root, page shape, and row shape match exactly;
5. all compatible references identify one strategy;
6. the callable is portable and importable;
7. current-row operation evidence matches the stored strategy;
8. the current output passes field and full-contract validation.

Opaque strategies are excluded unless `allow_opaque=True`. Conflicts, degenerate pages, stale callables, operation drift, or validation failures abstain. Yosoi reruns the strategy against the current row; it never serves a stored value.

## Contracts, specs, and recipes

Extractor fields use ContractSpec schema v2. The spec preserves structured generic annotations, import references, extractor configuration, resolver identity/version, defaults, and importable `Annotated` metadata.

`render_contract_py()` round-trips portable fields as `ys.Extractor(...)`. Process-local callable references are intentionally rejected during rendering. Nested `ys.Contract` fields that themselves contain extractor fields are currently rejected at contract definition time; use a flat extractor field returning a Pydantic model instead.

See also:

- [`policy-files.md`](policy-files.md)
- [`fingerprinting-stack.md`](fingerprinting-stack.md)
- [`recipes.md`](recipes.md)

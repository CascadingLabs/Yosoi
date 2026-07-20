"""Deterministic per-row extractor field behavior."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Sequence
from typing import Annotated, Literal

import pytest
from annotated_types import Gt
from pydantic import BaseModel, BeforeValidator, model_validator

import yosoi as ys
from yosoi.core.extraction import ContentExtractor
from yosoi.core.resolve import build_cache_from_selectors, resolve_async
from yosoi.fingerprints import FingerprintStore
from yosoi.models.extraction import ExtractorResolutionError
from yosoi.models.results import FetchResult


def explicit_links(row: ys.ExtractionRow) -> list[str]:
    """Return row-scoped links for explicit-resolution tests."""
    return row.xpath('.//a/@href').getall()


async def async_links(row: ys.ExtractionRow) -> list[str]:
    """Return row-scoped links through an awaitable extractor."""
    return row.xpath('.//a/@href').getall()


def alternate_links(row: ys.ExtractionRow) -> list[str]:
    """Return the same evidence through a conflicting resolver identity."""
    return row.xpath('.//a/@href').getall()


EXPLICIT_LINKS_REF = f'{explicit_links.__module__}:{explicit_links.__qualname__}'
ALTERNATE_LINKS_REF = f'{alternate_links.__module__}:{alternate_links.__qualname__}'


class PlannedProfile(BaseModel):
    platform: str
    url: str

    @classmethod
    def from_url(cls, url: str) -> PlannedProfile | None:
        if 'linkedin.com/' in url:
            return cls(platform='linkedin', url=url)
        if 'x.com/' in url:
            return cls(platform='x', url=url)
        return None


class BoundCompany(ys.Contract):
    name: str = ys.Extractor()
    links: list[str] = ys.Extractor()

    @ys.extraction(name)
    async def arbitrary_name(row: ys.ExtractionRow) -> str:
        return str(row.text('h1'))

    @ys.extraction(links)
    def arbitrary_links(row: ys.ExtractionRow) -> list[str]:
        return row.attribute('a[href]', 'href')


_BATCH_CALLS: list[int] = []


class BatchedCompany(ys.Contract):
    root = ys.css('.company')

    name: str = ys.Extractor()
    links: list[str] = ys.Extractor()

    @ys.extractions(name, links)
    async def arbitrary_batch_name(row: ys.ExtractionRow) -> dict[str, object]:
        _BATCH_CALLS.append(row.index)
        return ys.values(name=row.text('h2'), links=row.attribute('a[href]', 'href'))


_BATCH_NO_MATCH_CALLS: list[int] = []


class OptionalBatchedCompany(ys.Contract):
    name: str | None = ys.Extractor()
    links: list[str] = ys.Extractor(default_factory=list)

    @ys.extractions(name, links)
    def no_values(row: ys.ExtractionRow) -> dict[str, object]:
        _BATCH_NO_MATCH_CALLS.append(row.index)
        raise ys.ExtractorNoMatch()


def rich_links_html(value: str) -> str:
    """Build a non-degenerate page shape with one value-varying link."""
    return (
        '<html><body><header><h1>Company</h1></header><main><section><article>'
        f'<a class="target" href="/{value}">Visit</a><p>Details</p>'
        '</article></section></main><footer><nav><a href="/help">Help</a></nav></footer></body></html>'
    )


def no_match(_row: ys.ExtractionRow) -> list[str]:
    """Abstain without treating absence as an implementation failure."""
    raise ys.ExtractorNoMatch('fixture has no value')


def runtime_values(row: ys.ExtractionRow) -> list[str]:
    """Read acquired runtime evidence for pure extraction tests."""
    return row.runtime_values()


async def async_generator_values(_row: ys.ExtractionRow):
    """Return an invalid asynchronous stream for resolution tests."""
    yield 'value'


def invalid_integer(_row: ys.ExtractionRow) -> str:
    """Return PII-shaped invalid output for diagnostic privacy tests."""
    return 'private@example.test'


def constant_values(_row: ys.ExtractionRow) -> list[str]:
    """Return a value without observing row evidence."""
    return ['constant']


def negative_integer(_row: ys.ExtractionRow) -> int:
    """Return a value rejected by a positive-number constraint."""
    return -1


def string_integer(_row: ys.ExtractionRow) -> str:
    """Return a value accepted by an importable ``BeforeValidator``."""
    return '7'


def parse_integer(value: object) -> int:
    """Parse an integer for annotation metadata round-trip tests."""
    return int(str(value))


class HookValue(BaseModel):
    """Value with a type-directed extractor hook."""

    value: str

    @classmethod
    def __yosoi_extract__(cls, row: ys.ExtractionRow) -> Iterable[HookValue]:
        """Return values from this row only."""
        return [cls(value=value) for value in row.css('.hook::text').getall()]


class RegistryValue(BaseModel):
    """Value extracted through the exact annotation registry."""

    value: str


def registry_values(row: ys.ExtractionRow) -> list[RegistryValue]:
    """Return exact registry values."""
    return [RegistryValue(value=value) for value in row.css('.registry::text').getall()]


ys.register_extractor(list[RegistryValue], registry_values, key='tests.registry-values', version='1')


async def test_marker_is_required_and_not_a_model_value() -> None:
    assert inspect.iscoroutinefunction(ys.extract)

    class Required(ys.Contract):
        values: list[str] = ys.Extractor(using=explicit_links)

    field = Required.model_fields['values']
    assert field.is_required()
    assert isinstance(field.json_schema_extra, dict)
    assert Required(values=['x']).values == ['x']


async def test_resolution_precedence_and_all_local_paths() -> None:
    class AllPaths(ys.Contract):
        explicit: list[str] = ys.Extractor(using=explicit_links)
        method: list[str] = ys.Extractor(key='tests.method', version='1')
        hooked: list[HookValue] = ys.Extractor()
        registered: list[RegistryValue] = ys.Extractor()

        @staticmethod
        def extract_explicit(_row: ys.ExtractionRow) -> list[str]:
            return ['wrong-precedence']

        @staticmethod
        def extract_method(row: ys.ExtractionRow) -> list[str]:
            return row.css('.method::text').getall()

    records = await ys.extract(
        '<a href="/one"></a><span class="method">m</span><span class="hook">h</span><span class="registry">r</span>',
        AllPaths,
        url='https://example.test/',
    )

    assert records == [
        {
            'explicit': ['/one'],
            'method': ['m'],
            'hooked': [{'value': 'h'}],
            'registered': [{'value': 'r'}],
        }
    ]


async def test_repeated_root_scopes_selector_and_extractor_fields_to_same_row() -> None:
    class Row(ys.Contract):
        root = ys.css('.row')
        name: str = ys.Field(selector='.name')
        links: list[str] = ys.Extractor(using=explicit_links)

    records = await ys.extract(
        '<div class="row"><b class="name">One</b><a href="/1"></a></div>'
        '<div class="row"><b class="name">Two</b><a href="/2"></a></div>',
        Row,
    )

    assert records == [{'name': 'One', 'links': ['/1']}, {'name': 'Two', 'links': ['/2']}]


async def test_root_scope_fingerprint_is_stable_across_selector_representations() -> None:
    class Row(ys.Contract):
        root = ys.css('.row')
        links: list[str] = ys.Extractor(using=explicit_links)

    html = '<article class="row"><a href="/one"></a></article>'
    typed = ContentExtractor(contract=Row)
    bare = ContentExtractor(contract=Row)
    assert await typed.extract_items_async('', html, {}, Row.get_root())
    assert await bare.extract_items_async('', html, {}, '.row')

    assert typed.last_extractor_fingerprints[0].root_scope == bare.last_extractor_fingerprints[0].root_scope


async def test_optional_no_match_uses_default_but_required_fails() -> None:
    class OptionalValue(ys.Contract):
        values: list[str] = ys.Extractor(using=no_match, default_factory=list)

    assert await ys.extract('<main></main>', OptionalValue) == [{'values': []}]

    class RequiredValue(ys.Contract):
        values: list[str] = ys.Extractor(using=no_match)

    with pytest.raises(ys.ExtractorFieldError, match='no_match'):
        await ys.extract('<main></main>', RequiredValue)


async def test_unresolved_extractors_fail_and_async_methods_are_awaited() -> None:
    class Missing(ys.Contract):
        value: str = ys.Extractor()

    with pytest.raises(ExtractorResolutionError, match='no exact deterministic extractor'):
        await ys.extract('<main></main>', Missing)

    class AsyncMethod(ys.Contract):
        value: str = ys.Extractor(key='tests.async-method', version='1')

        @staticmethod
        async def extract_value(_row: ys.ExtractionRow) -> str:
            return 'x'

    assert await ys.extract('<main></main>', AsyncMethod) == [{'value': 'x'}]


async def test_async_extractor_runs_on_the_callers_event_loop() -> None:
    class AsyncLinks(ys.Contract):
        values: list[str] = ys.Extractor(using=async_links)

    assert await ys.extract('<a href="/async"></a>', AsyncLinks) == [{'values': ['/async']}]


async def test_extractor_fields_are_absent_from_selector_metadata_and_round_trip() -> None:
    class Portable(ys.Contract):
        title: str = ys.Field(selector='h1')
        links: list[str] = ys.Extractor(using=explicit_links, default_factory=list, version='7')

    assert Portable.discovery_field_names() == {'title'}
    assert set(Portable.to_selector_model().model_fields) == {'root'}
    assert Portable.field_descriptions() == {}
    spec = Portable.to_spec()
    restored = spec.to_contract()
    assert spec.schema_version == 2
    assert restored.to_spec().fingerprint == spec.fingerprint
    assert await ys.extract('<h1>T</h1><a href="/x"></a>', restored) == [{'title': 'T', 'links': ['/x']}]


async def test_pure_resolve_reruns_extractor_only_and_mixed_contracts() -> None:
    class ExtractorOnly(ys.Contract):
        links: list[str] = ys.Extractor(using=explicit_links)

    extractor_spec = ExtractorOnly.to_spec()
    assert await resolve_async(extractor_spec, '<a href="/fresh"></a>', {}, 'example.test') == [{'links': ['/fresh']}]

    class Mixed(ys.Contract):
        title: str = ys.Field(selector='h1')
        links: list[str] = ys.Extractor(using=explicit_links)

    mixed_spec = Mixed.to_spec()
    cache = build_cache_from_selectors(
        'example.test',
        mixed_spec.fingerprint,
        {'title': {'primary': {'type': 'css', 'value': 'h1'}}},
    )
    assert await resolve_async(mixed_spec, '<h1>Current</h1><a href="/current"></a>', cache, 'example.test') == [
        {'title': 'Current', 'links': ['/current']}
    ]


async def test_pipeline_extractor_only_bypasses_discovery_with_llm_disabled(tmp_path, monkeypatch) -> None:
    class ExtractorOnly(ys.Contract):
        values: list[str] = ys.Extractor(using=explicit_links)

    class Fetcher:
        supports_browse = False

        async def fetch(self, url: str, **_kwargs: object) -> FetchResult:
            return FetchResult(url=url, html='<a href="/deterministic"></a>', status_code=200)

    monkeypatch.chdir(tmp_path)
    async with ys.Pipeline(None, contract=ExtractorOnly, quiet=True, allow_llm=False) as pipeline:

        async def forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError('selector discovery must not run')

        pipeline.discovery.discover_selectors = forbidden
        records = [item async for item in pipeline.scrape('https://example.test/', fetcher=Fetcher())]

    assert records == [{'values': ['/deterministic']}]
    assert pipeline.last_llm_used is False
    assert pipeline.last_selector_source == 'extractor'


async def test_prefetched_runtime_evidence_is_available_without_leaking_values() -> None:
    class RuntimeSignals(ys.Contract):
        values: list[str] = ys.Extractor(using=runtime_values)

    assert await ys.extract(
        '<main></main>',
        RuntimeSignals,
        runtime_evidence={'resource_urls': ['https://cdn.example.test/alita-embed.js']},
    ) == [{'values': ['https://cdn.example.test/alita-embed.js']}]

    coordinator = ContentExtractor(contract=RuntimeSignals)
    assert await coordinator.extract_content_with_html_async(
        'https://example.test/',
        '<main></main>',
        {},
        runtime_evidence={
            'resource_urls': ['https://cdn.example.test/loader.js?token=secret'],
            'endpoints': ['https://api.example.test/private/customer-1'],
        },
    ) == {
        'values': [
            'https://cdn.example.test/loader.js?token=secret',
            'https://api.example.test/private/customer-1',
        ]
    }

    fingerprint = coordinator.last_extractor_fingerprints[0]
    payload = fingerprint.model_dump_json()
    assert fingerprint.evidence_sources == ('runtime',)
    assert 'loader.js' not in payload
    assert 'customer-1' not in payload
    assert 'secret' not in payload


async def test_runtime_evidence_treats_one_string_as_one_value_and_rejects_non_strings() -> None:
    row = ys.ExtractionRow('<main></main>', runtime_evidence={'resource_urls': 'https://cdn.example.test/app.js'})
    assert row.runtime_values('resource_urls') == ['https://cdn.example.test/app.js']

    with pytest.raises(TypeError, match='must contain only strings'):
        ys.ExtractionRow('<main></main>', runtime_evidence={'resource_urls': ['ok', 3]})  # type: ignore[list-item]


async def test_extractor_diagnostics_reset_between_pages() -> None:
    class RuntimeSignals(ys.Contract):
        values: list[str] = ys.Extractor(using=runtime_values)

    coordinator = ContentExtractor(contract=RuntimeSignals)
    await coordinator.extract_content_with_html_async('', '<main></main>', {}, runtime_evidence={'first': ['one']})
    await coordinator.extract_content_with_html_async('', '<main></main>', {}, runtime_evidence={'second': ['two']})

    assert len(coordinator.last_extractor_diagnostics) == 1
    assert len(coordinator.last_extractor_fingerprints) == 1


async def test_async_generators_are_rejected_during_binding() -> None:
    with pytest.raises(ExtractorResolutionError, match='async generator'):

        class AsyncGenerator(ys.Contract):
            values: list[str] = ys.Extractor(using=async_generator_values)


async def test_invalid_process_local_callable_does_not_poison_its_key() -> None:
    class InvalidCallable:
        def __call__(self, _row: ys.ExtractionRow, extra: object) -> str:
            return str(extra)

    with pytest.raises(ExtractorResolutionError, match='exactly one positional'):
        ys.Extractor(using=InvalidCallable(), key='tests.runtime-invalid', version='1')

    valid = lambda _row: ['valid']  # noqa: E731
    ys.Extractor(using=valid, key='tests.runtime-invalid', version='1')


async def test_extraction_row_public_context_is_read_only() -> None:
    row = ys.ExtractionRow(
        '<main></main>',
        url='https://example.test/',
        index=2,
        root_scope='cards',
        config={'nested': {'values': ['one']}},
    )

    with pytest.raises(AttributeError):
        row.url = 'https://attacker.test/'  # type: ignore[misc]
    with pytest.raises(AttributeError):
        row.index = 9  # type: ignore[misc]
    with pytest.raises(AttributeError):
        row.root_scope = 'other'  # type: ignore[misc]
    with pytest.raises(TypeError):
        row.config['new'] = 'value'  # type: ignore[index]
    with pytest.raises(TypeError):
        row.config['nested']['new'] = 'value'
    assert row.config['nested']['values'] == ('one',)


async def test_nested_contract_extractors_fail_at_definition_instead_of_runtime() -> None:
    class Child(ys.Contract):
        links: list[str] = ys.Extractor(using=explicit_links)

    with pytest.raises(TypeError, match='nested Contracts containing extractor fields are not supported'):

        class Parent(ys.Contract):
            child: Child


async def test_structured_annotations_round_trip_variadic_tuple_and_literal(tmp_path) -> None:
    class Structured(ys.Contract):
        aliases: tuple[str, ...] = ys.Extractor(using=explicit_links)
        channel: Literal['email', 'phone'] = ys.Extractor(using=explicit_links)
        hooked: list[HookValue] = ys.Extractor(using=explicit_links)

    serialized = Structured.to_spec().model_dump_json()
    restored = ys.ContractSpec.model_validate_json(serialized).to_contract()

    assert restored.model_fields['aliases'].annotation == tuple[str, ...]
    assert restored.model_fields['channel'].annotation == Literal['email', 'phone']
    assert restored.model_fields['hooked'].annotation == list[HookValue]
    rendered = ys.recipe.render_contract_py(Structured.to_spec())
    assert "_load_ref('typing:Literal')" in rendered
    assert 'tuple[str, ...]' in rendered
    contract_path = tmp_path / 'structured_contract.py'
    contract_path.write_text(rendered, encoding='utf-8')
    compiled = ys.recipe.compile_contract(f'{contract_path}:Structured')
    assert compiled.fingerprint == Structured.to_spec().fingerprint


async def test_prefetched_api_reports_missing_nested_required_selectors() -> None:
    class Child(ys.Contract):
        title: str
        subtitle: str = 'fallback'

    class Parent(ys.Contract):
        child: Child

    assert Parent.required_discovery_field_names() == {'child_title'}
    with pytest.raises(ValueError, match='child_title'):
        await ys.extract('<h1>Title</h1>', Parent)


async def test_prefetched_api_rejects_action_fields_it_cannot_execute() -> None:
    class BrowserAction(ys.Contract):
        signal: str = ys.js("'value'")

    with pytest.raises(ValueError, match='cannot execute browser or download action fields: signal'):
        await ys.extract('<main></main>', BrowserAction)


async def test_invalid_extractor_config_fails_when_the_field_is_declared() -> None:
    with pytest.raises(TypeError, match='config must be JSON-serializable'):
        ys.Extractor(config={'unsafe': object()})


async def test_contract_spec_preserves_annotated_constraints_and_validators(tmp_path) -> None:
    class Positive(ys.Contract):
        value: Annotated[int, Gt(0)] = ys.Extractor(using=negative_integer)

    restored_positive = ys.ContractSpec.model_validate_json(Positive.to_spec().model_dump_json()).to_contract()
    for contract in (Positive, restored_positive):
        with pytest.raises(ys.ExtractorFieldError, match='validation_failure'):
            await ys.extract('<main></main>', contract)

    class Parsed(ys.Contract):
        value: Annotated[int, BeforeValidator(parse_integer)] = ys.Extractor(using=string_integer)

    parsed_spec = Parsed.to_spec()
    restored_parsed = ys.ContractSpec.model_validate_json(parsed_spec.model_dump_json()).to_contract()
    assert await ys.extract('<main></main>', restored_parsed) == [{'value': 7}]

    path = tmp_path / 'annotated_contract.py'
    path.write_text(ys.recipe.render_contract_py(parsed_spec), encoding='utf-8')
    generated_spec = ys.recipe.compile_contract(f'{path}:Parsed')
    assert generated_spec.fingerprint == parsed_spec.fingerprint
    assert await ys.extract('<main></main>', generated_spec.to_contract()) == [{'value': 7}]


async def test_generated_contract_rejects_process_local_extractor_references() -> None:
    local = lambda _row: ['value']  # noqa: E731

    class LocalContract(ys.Contract):
        values: list[str] = ys.Extractor(using=local, key='tests.runtime-render', version='1')

    with pytest.raises(ValueError, match='cannot render process-local extractor'):
        ys.recipe.render_contract_py(LocalContract.to_spec())


async def test_process_local_keys_cannot_silently_rebind_to_different_callables() -> None:
    first = lambda _row: ['first']  # noqa: E731
    second = lambda _row: ['second']  # noqa: E731
    ys.Extractor(using=first, key='tests.runtime-key-conflict', version='1')

    with pytest.raises(ExtractorResolutionError, match='already bound to a different callable'):
        ys.Extractor(using=second, key='tests.runtime-key-conflict', version='1')


async def test_validation_failure_diagnostics_do_not_include_extracted_values() -> None:
    class PrivateValue(ys.Contract):
        value: int = ys.Extractor(using=invalid_integer)

    with pytest.raises(ys.ExtractorFieldError) as caught:
        await ys.extract('<main></main>', PrivateValue)

    assert 'private@example.test' not in str(caught.value)
    assert 'validation_failure' in str(caught.value)


async def test_evidence_free_extractors_are_marked_opaque() -> None:
    class Constant(ys.Contract):
        values: list[str] = ys.Extractor(using=constant_values)

    coordinator = ContentExtractor(contract=Constant)
    await coordinator.extract_content_with_html_async('', '<main></main>', {})

    assert coordinator.last_extractor_fingerprints[0].opaque is True
    assert coordinator.last_extractor_fingerprints[0].operations == ()


async def test_extractor_reference_reuse_requires_explicit_read_and_yellow_trust(tmp_path) -> None:
    class Learned(ys.Contract):
        values: list[str] = ys.Extractor(using=explicit_links)

    store = FingerprintStore(tmp_path / 'fingerprints')
    writer = ContentExtractor(
        contract=Learned,
        policy=ys.Policy(extractor=ys.ExtractorPolicy(reference_writes=True)),
        fingerprint_store=store,
    )
    extracted = await writer.extract_content_with_html_async(
        'https://example.test/company/1',
        rich_links_html('first'),
        {},
    )
    assert extracted == {'values': ['/first', '/help']}
    Learned.model_validate(extracted)
    writer.persist_validated_references()
    assert len(store.list_field_references(field_name='values')) == 1
    stored_payload = ''.join(path.read_text(encoding='utf-8') for path in store.root.rglob('*.json'))
    assert '/first' not in stored_payload
    assert '/company/1' not in stored_payload

    class Reused(ys.Contract):
        values: list[str] = ys.Extractor()

    with pytest.raises(ExtractorResolutionError, match='no exact deterministic extractor'):
        ContentExtractor(
            contract=Reused,
            policy=ys.Policy(
                extractor=ys.ExtractorPolicy(generalized_reads=True, allowed_references=(EXPLICIT_LINKS_REF,))
            ),
            fingerprint_store=store,
        )

    reader = ContentExtractor(
        contract=Reused,
        policy=ys.Policy(
            trust_tier='yellow',
            extractor=ys.ExtractorPolicy(generalized_reads=True, allowed_references=(EXPLICIT_LINKS_REF,)),
        ),
        fingerprint_store=store,
    )
    assert await reader.extract_content_with_html_async(
        'https://example.test/company/2',
        rich_links_html('second'),
        {},
    ) == {'values': ['/second', '/help']}
    assert reader.last_extractor_fingerprints[0].resolver_source == 'generalized'


async def test_pure_api_requires_explicit_store_for_extractor_reference_io(tmp_path) -> None:
    class Contact(ys.Contract):
        values: list[str] = ys.Extractor(using=explicit_links)

    policy = ys.Policy(extractor=ys.ExtractorPolicy(reference_writes=True))
    with pytest.raises(ValueError, match='requires fingerprint_store'):
        await ys.extract('<a href="/one"></a>', Contact, policy=policy)

    store = FingerprintStore(tmp_path / 'fingerprints')
    assert await ys.extract(
        '<a href="/one"></a>',
        Contact,
        policy=policy,
        fingerprint_store=store,
    ) == [{'values': ['/one']}]
    assert store.list_field_references(field_name='values')


async def test_reference_writes_and_generalized_reads_are_opt_in_and_current_value_only(tmp_path) -> None:
    class Local(ys.Contract):
        links: list[str] = ys.Extractor(using=explicit_links)

    store = FingerprintStore(tmp_path)
    write_policy = ys.Policy(extractor=ys.ExtractorPolicy(reference_writes=True))
    with pytest.raises(ValueError, match='requires fingerprint_store'):
        await ys.extract(rich_links_html('one'), Local, policy=write_policy)

    written = await ys.extract(
        rich_links_html('one'),
        Local,
        url='https://example.test/company/1?email=private@example.test',
        policy=write_policy,
        fingerprint_store=store,
    )
    assert written[0]['links'][0] == '/one'
    references = store.list_field_references(field_name='links')
    assert len(references) == 1
    payload = references[0].model_dump_json()
    assert '/one' not in payload
    assert 'private@example.test' not in payload

    class Generalized(ys.Contract):
        links: list[str] = ys.Extractor()

    strict_policy = ys.Policy(
        extractor=ys.ExtractorPolicy(generalized_reads=True, allowed_references=(EXPLICIT_LINKS_REF,)),
        trust_tier='strict',
    )
    with pytest.raises(ExtractorResolutionError, match='no exact deterministic extractor'):
        await ys.extract(
            rich_links_html('two'),
            Generalized,
            url='https://example.test/company/2',
            policy=strict_policy,
            fingerprint_store=store,
        )

    read_policy = ys.Policy(
        extractor=ys.ExtractorPolicy(generalized_reads=True, allowed_references=(EXPLICIT_LINKS_REF,)),
        trust_tier='yellow',
    )
    records = await ys.extract(
        rich_links_html('two'),
        Generalized,
        url='https://example.test/company/2',
        policy=read_policy,
        fingerprint_store=store,
    )
    assert records[0]['links'][0] == '/two'
    assert '/one' not in records[0]['links']


async def test_generalized_reference_requires_current_operation_match(tmp_path) -> None:
    class Local(ys.Contract):
        links: list[str] = ys.Extractor(using=explicit_links)

    source_store = FingerprintStore(tmp_path / 'source')
    policy = ys.Policy(extractor=ys.ExtractorPolicy(reference_writes=True))
    await ys.extract(
        rich_links_html('source'),
        Local,
        url='https://example.test/company/1',
        policy=policy,
        fingerprint_store=source_store,
    )
    reference = source_store.list_field_references(field_name='links')[0]
    assert reference.extractor is not None
    mismatched_strategy = reference.extractor.model_copy(update={'operations': ('different-operation',)})
    mismatched = reference.model_copy(update={'extractor': mismatched_strategy})
    mismatch_store = FingerprintStore(tmp_path / 'mismatch')
    mismatch_store.save_field_reference(mismatched)

    class Generalized(ys.Contract):
        links: list[str] = ys.Extractor()

    read_policy = ys.Policy(
        extractor=ys.ExtractorPolicy(generalized_reads=True, allowed_references=(EXPLICIT_LINKS_REF,)),
        trust_tier='yellow',
    )
    coordinator = ContentExtractor(contract=Generalized, policy=read_policy, fingerprint_store=mismatch_store)
    with pytest.raises(ys.ExtractorFieldError, match='generalization_mismatch'):
        await coordinator.extract_content_with_html_async(
            'https://example.test/company/2',
            rich_links_html('current'),
            {},
        )
    assert any(item['category'] == 'generalization_mismatch' for item in coordinator.last_extractor_diagnostics)


async def test_reference_write_waits_for_full_contract_validation(tmp_path) -> None:
    class Rejected(ys.Contract):
        values: list[str] = ys.Extractor(using=constant_values)

        @model_validator(mode='after')
        def reject_record(self) -> Rejected:
            raise ValueError('cross-field contract rejection')

    store = FingerprintStore(tmp_path)
    policy = ys.Policy(extractor=ys.ExtractorPolicy(reference_writes=True))
    with pytest.raises(ValueError, match='validation failed for extracted row'):
        await ys.extract('<main></main>', Rejected, policy=policy, fingerprint_store=store)

    assert store.list_field_references(field_name='values') == []


async def test_conflicting_generalized_resolvers_abstain(tmp_path) -> None:
    class First(ys.Contract):
        links: list[str] = ys.Extractor(using=explicit_links)

    class Second(ys.Contract):
        links: list[str] = ys.Extractor(using=alternate_links)

    store = FingerprintStore(tmp_path)
    policy = ys.Policy(extractor=ys.ExtractorPolicy(reference_writes=True))
    for contract in (First, Second):
        await ys.extract(
            rich_links_html('source'),
            contract,
            url='https://example.test/company/1',
            policy=policy,
            fingerprint_store=store,
        )
    assert len(store.list_field_references(field_name='links')) == 2

    class Generalized(ys.Contract):
        links: list[str] = ys.Extractor()

    read_policy = ys.Policy(
        extractor=ys.ExtractorPolicy(
            generalized_reads=True,
            allowed_references=(EXPLICIT_LINKS_REF, ALTERNATE_LINKS_REF),
        ),
        trust_tier='yellow',
    )
    coordinator = ContentExtractor(contract=Generalized, policy=read_policy, fingerprint_store=store)
    with pytest.raises(ys.ExtractorFieldError, match='unresolved'):
        await coordinator.extract_content_with_html_async(
            'https://example.test/company/2',
            rich_links_html('current'),
            {},
        )
    assert any(item['category'] == 'generalization_conflict' for item in coordinator.last_extractor_diagnostics)


async def test_runtime_fingerprint_is_content_free_and_value_stable() -> None:
    class Contact(ys.Contract):
        values: list[str] = ys.Extractor(using=explicit_links)

    first = ContentExtractor(contract=Contact)
    second = ContentExtractor(contract=Contact)
    assert await first.extract_content_with_html_async(
        'https://example.test/company/1?email=one@example.test',
        '<a href="mailto:one@example.test">one@example.test</a>',
        {},
    )
    assert await second.extract_content_with_html_async(
        'https://example.test/company/2?email=two@example.test',
        '<a href="mailto:two@example.test">two@example.test</a>',
        {},
    )
    left = first.last_extractor_fingerprints[0]
    right = second.last_extractor_fingerprints[0]
    payload = left.model_dump_json()
    assert left.row == right.row
    assert left.operations == right.operations
    assert 'one@example.test' not in payload
    assert 'mailto:' not in payload
    assert '?email=' not in payload


async def test_fluent_css_plan_uses_annotation_cardinality_without_root() -> None:
    class Company(ys.Contract):
        name: str = ys.css('h1').text()
        socials: list[PlannedProfile] = ys.css('a[href]').attr('href').map(PlannedProfile.from_url).compact()

    records = await ys.extract(
        '<h1>Acme</h1><a href="https://linkedin.com/company/acme"></a><a href="/about"></a>',
        Company,
    )

    assert records == [
        {
            'name': 'Acme',
            'socials': [{'platform': 'linkedin', 'url': 'https://linkedin.com/company/acme'}],
        }
    ]
    assert Company.model_fields['socials'].is_required()

    restored = ys.ContractSpec.model_validate_json(Company.to_spec().model_dump_json()).to_contract()
    assert (
        await ys.extract(
            '<h1>Acme</h1><a href="https://linkedin.com/company/acme"></a><a href="/about"></a>',
            restored,
        )
        == records
    )


async def test_fluent_plan_recognizes_abstract_collection_annotations() -> None:
    class AbstractCollection(ys.Contract):
        values: Sequence[str] = ys.css('li').text()

    assert await ys.extract('<li>One</li><li>Two</li>', AbstractCollection) == [{'values': ['One', 'Two']}]


async def test_fluent_plan_rejects_invalid_mapper_before_row_execution() -> None:
    class Invalid(ys.Contract):
        value: str = ys.css('h1').text().map(pow)

    with pytest.raises(ExtractorResolutionError, match='exactly one positional'):
        await ys.extract('<h1>Acme</h1>', Invalid)


async def test_fluent_xpath_plan_and_contract_spec_round_trip(tmp_path) -> None:
    class Company(ys.Contract):
        names: list[str] = ys.xpath('//h2').text()

    spec = Company.to_spec()
    restored = spec.to_contract()
    html = '<h2>One</h2><h2>Two</h2>'

    assert await ys.extract(html, restored) == [{'names': ['One', 'Two']}]
    rendered = ys.recipe.render_contract_py(spec)
    assert "ys.xpath('//h2').text()" in rendered
    path = tmp_path / 'plan_contract.py'
    path.write_text(rendered, encoding='utf-8')
    compiled = ys.recipe.compile_contract(f'{path}:Company')
    assert await ys.extract(html, compiled.to_contract()) == [{'names': ['One', 'Two']}]


async def test_bound_extraction_decorator_needs_no_staticmethod_or_name_convention() -> None:
    assert '__yosoi_binding_token__' not in repr(BoundCompany.extractor_fields())
    assert await ys.extract('<h1>Acme</h1><a href="/about"></a>', BoundCompany) == [
        {'name': 'Acme', 'links': ['/about']}
    ]


async def test_multi_field_extraction_executes_once_per_root_row(tmp_path) -> None:
    _BATCH_CALLS.clear()
    html = (
        '<article class="company"><h2>One</h2><a href="/one"></a></article>'
        '<article class="company"><h2>Two</h2><a href="/two"></a></article>'
    )

    assert await ys.extract(html, BatchedCompany) == [
        {'name': 'One', 'links': ['/one']},
        {'name': 'Two', 'links': ['/two']},
    ]
    assert _BATCH_CALLS == [0, 1]

    _BATCH_CALLS.clear()
    restored = BatchedCompany.to_spec().to_contract()
    assert await ys.extract(html, restored) == [
        {'name': 'One', 'links': ['/one']},
        {'name': 'Two', 'links': ['/two']},
    ]
    assert _BATCH_CALLS == [0, 1]

    rendered = ys.recipe.render_contract_py(BatchedCompany.to_spec())
    assert "batch_fields=('name', 'links')" in rendered
    assert 'yosoi.types.field:_extractor_batch' in rendered
    path = tmp_path / 'batch_contract.py'
    path.write_text(rendered, encoding='utf-8')
    compiled = ys.recipe.compile_contract(f'{path}:BatchedCompany').to_contract()
    _BATCH_CALLS.clear()
    assert await ys.extract(html, compiled)
    assert _BATCH_CALLS == [0, 1]


async def test_multi_field_no_match_is_cached_once_for_defaulted_fields() -> None:
    _BATCH_NO_MATCH_CALLS.clear()

    assert await ys.extract('<main></main>', OptionalBatchedCompany) == [{'name': None, 'links': []}]
    assert _BATCH_NO_MATCH_CALLS == [0]


async def test_multi_field_extractor_rejects_unexpected_output_keys() -> None:
    class Typo(ys.Contract):
        value: str | None = ys.Extractor(key='batch-output-typo', version='1')

        @ys.extractions(value)
        def batch(row: ys.ExtractionRow) -> dict[str, str]:
            return ys.values(vlaue=str(row.text('h1')))

    with pytest.raises(TypeError, match=r"unexpected field\(s\): 'vlaue'"):
        await ys.extract('<h1>Acme</h1>', Typo)


def test_decorator_rejects_reused_field_marker() -> None:
    marker = ys.Extractor(default='missing')

    with pytest.raises(TypeError, match='marker was reused'):

        class Reused(ys.Contract):
            first: str = marker
            second: str = marker

            @ys.extraction(first)
            def selected(row: ys.ExtractionRow) -> str:
                return str(row.text('h1'))


def test_extraction_row_json_ld_and_context_helpers_are_network_free() -> None:
    html = """
    <main><h1> Acme </h1><a href='/one'>One</a>
      <script type='application/ld+json'>{"org":{"name":"Acme","people":[{"name":"Ada"}]}}</script>
      <script type='application/ld+json'>not-json</script>
    </main>
    """
    row = ys.ExtractionRow(
        html,
        url='https://example.test/acme',
        index=2,
        root_scope='scope',
        config={'nested': {'items': [1, 2]}, 'flags': {'a'}},
        runtime_evidence={'urls': ['one', 'two'], 'single': 'three'},
    )

    assert row.url == 'https://example.test/acme'
    assert row.index == 2
    assert row.root_scope == 'scope'
    assert row.html == html
    assert row.raw_html == html
    assert row.css('h1::text').get().strip() == 'Acme'
    assert row.xpath('.//a/@href').get() == '/one'
    assert row.attribute('a', 'href') == ['/one']
    assert row.attribute('.//a', 'href', xpath=True) == ['/one']
    assert row.text('h1') == 'Acme'
    assert row.text('.//h1', xpath=True, all=True) == ['Acme']
    assert row.json_ld() == [{'org': {'name': 'Acme', 'people': [{'name': 'Ada'}]}}]
    assert row.json_ld('org.name') == ['Acme']
    assert row.json_ld('org.people.*.name') == ['Ada']
    assert row.json_ld('org.people.0.name') == ['Ada']
    assert {'name': 'Ada'} in row.json_ld_mappings()
    assert row.runtime_values() == ['one', 'two', 'three']
    assert row.runtime_values('single') == ['three']
    assert row.config['nested']['items'] == (1, 2)
    assert row.config['flags'] == frozenset({'a'})
    assert {item.source for item in row.evidence} >= {'raw_html', 'dom', 'attribute', 'text', 'json_ld', 'runtime'}


@pytest.mark.parametrize(
    ('plan', 'message'),
    [
        ({'extra': True}, 'unexpected key'),
        ({}, 'missing its selector'),
        ({'selector': {'type': 'regex', 'value': 'x'}, 'operation': 'text'}, 'requires a CSS or XPath selector'),
        ({'selector': {'type': 'css', 'value': 'h1'}, 'operation': 'missing'}, 'unknown extractor plan'),
        (
            {'selector': {'type': 'css', 'value': 'a'}, 'operation': 'attribute'},
            'requires an attribute name',
        ),
        (
            {'selector': {'type': 'css', 'value': 'h1'}, 'operation': 'text', 'attribute': 'x'},
            'cannot configure an attribute',
        ),
        (
            {'selector': {'type': 'css', 'value': 'h1'}, 'operation': 'text', 'maps': 'bad'},
            'maps must be a list',
        ),
        (
            {'selector': {'type': 'css', 'value': 'h1'}, 'operation': 'text', 'compact': 'yes'},
            'compact must be a boolean',
        ),
    ],
)
def test_validate_extraction_plan_rejects_every_malformed_shape(plan, message) -> None:
    from yosoi.models.extraction import validate_extraction_plan

    with pytest.raises(ExtractorResolutionError, match=message):
        validate_extraction_plan(plan)


def test_extractor_annotation_identity_and_cardinality_helpers_cover_nested_shapes() -> None:
    import types
    from collections.abc import Sequence as AbcSequence

    from yosoi.models.extraction import (
        _cardinality_band,
        _hook_type,
        _plan_has_many_outputs,
        _value_cardinality_band,
        annotation_identity,
    )

    assert annotation_identity(str) == 'builtins:str'
    assert annotation_identity(type(None)) == 'builtins:None'
    assert annotation_identity(list[str]) == 'builtins:list[builtins:str]'
    assert annotation_identity(str | None).startswith('union[')
    assert _plan_has_many_outputs(list[str]) is True
    assert _plan_has_many_outputs(AbcSequence[str] | None) is True
    assert _plan_has_many_outputs(str) is False
    assert _hook_type(list[str]) is str
    assert _hook_type(str | None) is str
    assert _hook_type(str | int) is None
    assert _hook_type(types.GenericAlias(list, ())) is None
    assert [_cardinality_band(value) for value in (0, 1, 2, 5, 17)] == ['0', '1', '2-4', '5-16', '17+']
    assert [_value_cardinality_band(value) for value in (None, 'x', {}, [1, 2], iter([1]))] == [
        '0',
        '1',
        '1',
        '2-4',
        'many',
    ]


def test_callable_loading_and_signature_validation_fail_closed() -> None:
    from yosoi.models.extraction import _load_callable, _validate_callable, callable_reference

    def invalid_keyword_only(row, *, required):
        return row, required

    assert _load_callable('tests.unit.core.extraction.test_extractor_fields:explicit_links') is explicit_links
    assert callable_reference(explicit_links).endswith(':explicit_links')
    for reference, message in [
        ('missing', 'module:qualname'),
        ('missing_package:fn', 'cannot import extractor'),
        ('yosoi.models.extraction:_PLAN_CONFIG_KEY', 'not callable'),
    ]:
        with pytest.raises(ExtractorResolutionError, match=message):
            _load_callable(reference)
    with pytest.raises(ExtractorResolutionError, match='importable module-level'):
        callable_reference(lambda row: row)
    with pytest.raises(ExtractorResolutionError, match='exactly one positional'):
        _validate_callable(lambda: None, 'zero')
    with pytest.raises(ExtractorResolutionError, match='exactly one positional'):
        _validate_callable(invalid_keyword_only, 'kwonly')


def test_decorator_rejects_duplicate_explicit_strategy() -> None:
    with pytest.raises(TypeError, match='cannot be combined'):

        class Invalid(ys.Contract):
            name: str = ys.Extractor(using=string_integer)

            @ys.extraction(name)
            def another_strategy(row: ys.ExtractionRow) -> str:
                return str(row.text('h1'))

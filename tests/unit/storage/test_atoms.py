"""Field-atom store (P2): content-addressed identity, sharing, provenance, persistence."""

from __future__ import annotations

from yosoi.storage.atoms import AtomStore, FieldAtom, derive_atoms

SHAPE = 's1:abc123'


def _primary(value: str) -> dict:
    return {'type': 'css', 'value': value}


def test_key_is_domain_independent() -> None:
    a = FieldAtom(
        page_shape=SHAPE,
        region_role='.MjjYud',
        field_name='url',
        yosoi_type='url',
        selector=_primary('a::attr(href)'),
        domains_seen=['google.com'],
    )
    b = a.model_copy(update={'domains_seen': ['google.co.uk']})
    # Same shape+region+field+type → same identity regardless of which domain saw it.
    assert a.key == b.key


def test_derive_region_from_root_and_name_fallback() -> None:
    rooted = derive_atoms(SHAPE, 'OrganicResult', 'google.com', [('url', _primary('a::attr(href)'), '.MjjYud', 'url')])
    assert rooted[0].region_role == '.MjjYud'  # case preserved (CSS is case-sensitive)
    rootless = derive_atoms(SHAPE, 'OrganicResult', 'google.com', [('url', _primary('a::attr(href)'), None, 'url')])
    assert rootless[0].region_role == 'name:OrganicResult'


def test_upsert_new_then_merge_provenance() -> None:
    store = AtomStore()
    [atom] = derive_atoms(SHAPE, 'OrganicResult', 'google.com', [('url', _primary('a::attr(href)'), '.MjjYud', 'url')])
    assert store.upsert(atom) is True  # minted
    # Same atom seen on a mirror → merges, not a new atom.
    [mirror] = derive_atoms(
        SHAPE, 'OrganicResult', 'google.co.uk', [('url', _primary('a::attr(href)'), '.MjjYud', 'url')]
    )
    assert store.upsert(mirror) is False  # reused
    assert len(store) == 1
    stored = store.get(atom.key)
    assert stored is not None
    assert stored.domains_seen == ['google.co.uk', 'google.com']  # union, sorted


def test_different_contracts_share_one_atom() -> None:
    # OrganicResult and SearchResult both want url from the .MjjYud region — ONE atom.
    store = AtomStore()
    organic = derive_atoms(SHAPE, 'OrganicResult', 'google.com', [('url', _primary('a::attr(href)'), '.MjjYud', 'url')])
    search = derive_atoms(SHAPE, 'SearchResult', 'google.com', [('url', _primary('a::attr(href)'), '.MjjYud', 'url')])
    store.upsert_all(organic)
    new = store.upsert_all(search)
    assert new == 0  # SearchResult.url reused OrganicResult's atom
    assert len(store) == 1
    stored = store.get(organic[0].key)
    assert stored is not None
    assert stored.contracts == ['OrganicResult', 'SearchResult']  # both credited


def test_adding_a_field_mints_exactly_one_atom() -> None:
    # The headline: growing a contract discovers ONE new atom; the rest stay hits.
    store = AtomStore()
    store.upsert_all(
        derive_atoms(
            SHAPE,
            'OrganicResult',
            'google.com',
            [
                ('url', _primary('a::attr(href)'), '.MjjYud', 'url'),
                ('title', _primary('h3::text'), '.MjjYud', 'title'),
            ],
        )
    )
    assert len(store) == 2
    # Now a SearchResult adds a `snippet` field; url+title are reused.
    new = store.upsert_all(
        derive_atoms(
            SHAPE,
            'SearchResult',
            'google.com',
            [
                ('url', _primary('a::attr(href)'), '.MjjYud', 'url'),
                ('title', _primary('h3::text'), '.MjjYud', 'title'),
                ('snippet', _primary('.snippet::text'), '.MjjYud', 'text'),
            ],
        )
    )
    assert new == 1  # only snippet was new
    assert len(store) == 3


def test_conflict_recorded_not_silently_overwritten() -> None:
    store = AtomStore()
    a = FieldAtom(
        page_shape=SHAPE, region_role='.MjjYud', field_name='url', yosoi_type='url', selector=_primary('a::attr(href)')
    )
    bad = a.model_copy(update={'selector': _primary('span::text')})  # same key, different selector
    store.upsert(a)
    store.upsert(bad)
    assert store.conflicts  # surfaced
    assert store.get(a.key).selector == _primary('a::attr(href)')  # first-writer-wins


def test_jsonl_persistence_round_trip(tmp_path) -> None:
    path = tmp_path / 'atoms.jsonl'
    store = AtomStore(path)
    store.upsert_all(
        derive_atoms(
            SHAPE,
            'OrganicResult',
            'google.com',
            [
                ('url', _primary('a::attr(href)'), '.MjjYud', 'url'),
                ('title', _primary('h3::text'), '.MjjYud', 'title'),
            ],
        )
    )
    reloaded = AtomStore(path)
    assert len(reloaded) == 2
    keys = {a.key for a in reloaded.all()}
    assert keys == {a.key for a in store.all()}


# ── provenance / trust tiers ───────────────────────────────────────────────────


def test_source_defaults_to_llm() -> None:
    a = derive_atoms(SHAPE, 'C', 'd.com', [('url', _primary('a::attr(href)'), '.r', 'url')])[0]
    assert a.source == 'llm'


def test_derive_atoms_source_param() -> None:
    a = derive_atoms(SHAPE, 'C', 'd.com', [('url', _primary('a::attr(href)'), '.r', 'url')], source='verified')[0]
    assert a.source == 'verified'


def test_merge_upgrades_to_highest_trust_source() -> None:
    fp = derive_atoms(SHAPE, 'C', 'd1.com', [('url', _primary('a::attr(href)'), '.r', 'url')], source='fingerprint')
    ver = derive_atoms(SHAPE, 'C', 'd2.com', [('url', _primary('a::attr(href)'), '.r', 'url')], source='verified')
    # fingerprint first, then verified → upgrades
    s1 = AtomStore()
    s1.upsert_all(fp)
    s1.upsert_all(ver)
    assert s1.get(fp[0].key).source == 'verified'
    # verified first, then fingerprint → never downgrades
    s2 = AtomStore()
    s2.upsert_all(ver)
    s2.upsert_all(fp)
    assert s2.get(ver[0].key).source == 'verified'


# ── P4: self-versioned, migration-safe corpus (monolith + domain retired as identity) ──


def test_derive_atoms_stamps_scheme() -> None:
    from yosoi.storage.atoms import ATOM_SCHEME_VERSION

    a = derive_atoms(SHAPE, 'C', 'd.com', [('url', _primary('a::attr(href)'), '.r', 'url')])[0]
    assert a.scheme == ATOM_SCHEME_VERSION


def test_list_stale_by_scheme_reports_old_and_unversioned() -> None:
    from yosoi.storage.atoms import ATOM_SCHEME_VERSION

    store = AtomStore()
    store.upsert_all(derive_atoms(SHAPE, 'C', 'd.com', [('url', _primary('a::attr(href)'), '.r', 'url')]))  # current
    # a pre-versioning (empty-scheme) atom and an old-scheme atom are stale
    store.upsert(FieldAtom(page_shape=SHAPE, region_role='.old1', field_name='x', selector=_primary('x'), scheme=''))
    store.upsert(FieldAtom(page_shape=SHAPE, region_role='.old2', field_name='y', selector=_primary('y'), scheme='a0'))
    stale = set(store.list_stale_by_scheme(ATOM_SCHEME_VERSION))
    assert len(stale) == 2  # only the two non-current atoms
    # the current-scheme atom is NOT stale
    fresh = derive_atoms(SHAPE, 'C', 'd.com', [('url', _primary('a::attr(href)'), '.r', 'url')])[0]
    assert fresh.key not in stale


def test_monolith_and_domain_are_not_atom_identity() -> None:
    # P4: contract_signature (monolith) and the literal domain are NOT part of atom identity —
    # same (shape, region, field, type) from different contracts/domains share ONE key.
    a = derive_atoms(SHAPE, 'AdContract', 'a.com', [('url', _primary('x'), '.r', 'url')])[0]
    b = derive_atoms(SHAPE, 'OtherContract', 'b.co.uk', [('url', _primary('x'), '.r', 'url')])[0]
    assert a.key == b.key
    assert 'a.com' not in a.key  # domain lives in provenance, not the key
    assert 'AdContract' not in a.key  # contract name lives in provenance, not the key

"""P2 gated dual-write: an ACCEPTED contract set internalizes atoms; a REJECTED one does not."""

from __future__ import annotations

from pathlib import Path

from yosoi import api
from yosoi import types as ys
from yosoi.models.contract import Contract
from yosoi.storage.atoms import AtomStore

SERP = """<body>
  <div class="uEierd"><a href="https://ad.example/lp"><h3>Ad</h3></a></div>
  <div class="MjjYud"><a href="https://organic.example/1"><h3>One</h3></a></div>
</body>"""


class AdResult(Contract):
    """A paid advertisement result."""

    url: str = ys.Url()
    title: str = ys.Title()


class OrganicResult(Contract):
    """A natural organic result."""

    url: str = ys.Url()
    title: str = ys.Title()


def _smap(root: str) -> dict:
    return {
        'url': {'primary': {'type': 'css', 'value': 'a::attr(href)'}, 'root': {'type': 'css', 'value': root}},
        'title': {'primary': {'type': 'css', 'value': 'h3::text'}, 'root': {'type': 'css', 'value': root}},
    }


def _generic() -> dict:
    return {'url': {'primary': {'type': 'css', 'value': 'a::attr(href)'}}}


def test_accepted_set_dualwrites_atoms(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api, '_ATOM_STORE_PATH', str(tmp_path / 'atoms.jsonl'))
    collected = {
        'AdResult': (_smap('.uEierd'), SERP),
        'OrganicResult': (_smap('.MjjYud'), SERP),
    }
    api._run_discrimination_gates(
        {'https://google.com/search?q=x': collected},
        {'AdResult': AdResult, 'OrganicResult': OrganicResult},
    )
    store = AtomStore(tmp_path / 'atoms.jsonl')
    assert len(store) == 4  # 2 contracts x {url, title}
    types = {a.yosoi_type for a in store.all()}
    assert types == {'url', 'title'}
    regions = {a.region_role for a in store.all()}
    assert regions == {'.uEierd', '.MjjYud'}  # root selectors, case preserved


def test_rejected_set_writes_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api, '_ATOM_STORE_PATH', str(tmp_path / 'atoms.jsonl'))
    # Both use a bare `a` → overlapping regions → REJECTED → never internalized.
    collected = {
        'AdResult': (_generic(), SERP),
        'OrganicResult': (_generic(), SERP),
    }
    api._run_discrimination_gates(
        {'https://google.com/search?q=x': collected},
        {'AdResult': AdResult, 'OrganicResult': OrganicResult},
    )
    assert not Path(tmp_path / 'atoms.jsonl').exists()  # gate rejected → no corpus write

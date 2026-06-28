from __future__ import annotations

import json
from datetime import datetime, timezone

from click.testing import CliRunner

from yosoi.cli.main import main
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap
from yosoi.models.spec import ContractSpec, FieldSpec


def test_recipe_mint_inspect_check_and_install(tmp_path) -> None:
    contract_path = tmp_path / 'contract.json'
    selectors_path = tmp_path / 'selectors.json'
    recipe_path = tmp_path / 'recipe.json'
    cache_dir = tmp_path / 'cache'

    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    contract_path.write_text(contract.model_dump_json(), encoding='utf-8')

    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    selectors_path.write_text(snap_map.model_dump_json(), encoding='utf-8')

    runner = CliRunner()
    mint = runner.invoke(
        main,
        [
            'recipe',
            'mint',
            '--contract',
            str(contract_path),
            '--selectors',
            str(selectors_path),
            '--out',
            str(recipe_path),
            '--json',
        ],
    )
    assert mint.exit_code == 0, mint.output
    minted = json.loads(mint.output)
    assert minted['recipe_id'].startswith('sha256:')

    check = runner.invoke(main, ['recipe', 'check', str(recipe_path), '--recipe-id', minted['recipe_id'], '--json'])
    assert check.exit_code == 0, check.output

    inspect = runner.invoke(main, ['recipe', 'inspect', str(recipe_path), '--json'])
    assert inspect.exit_code == 0, inspect.output
    inspected = json.loads(inspect.output)
    assert inspected['contract'] == 'Product'
    assert inspected['domains'] == ['example.com']

    install = runner.invoke(main, ['recipe', 'install', str(recipe_path), '--cache-dir', str(cache_dir), '--json'])
    assert install.exit_code == 0, install.output
    installed = json.loads(install.output)
    assert installed['recipe_id'] == minted['recipe_id']

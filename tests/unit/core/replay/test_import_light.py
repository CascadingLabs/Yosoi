"""W3: replay hot path must stay geopy-free (CAS-87 import-light invariant).

geopy (+ geographiclib) is a DISCOVERY-time dep used only to bake literal coords
into a persisted TeleportSpec. Replay carries the literal coords, so importing the
replay runtime must NOT transitively pull geopy. We assert this in a CLEAN
subprocess — the in-test process may already have geopy loaded by the geocode
tests, so sys.modules here is not a reliable witness.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def _import_and_check(module: str) -> subprocess.CompletedProcess[str]:
    code = textwrap.dedent(
        f"""
        import sys
        import {module}  # noqa: F401
        leaked = sorted(m for m in sys.modules if m == 'geopy' or m.startswith('geopy.'))
        if leaked:
            print('LEAKED:' + ','.join(leaked))
            raise SystemExit(1)
        print('CLEAN')
        """
    )
    return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)


def test_replay_runtime_does_not_import_geopy():
    proc = _import_and_check('yosoi.core.replay.runtime')
    assert proc.returncode == 0, f'replay runtime leaked geopy: {proc.stdout}\n{proc.stderr}'
    assert 'CLEAN' in proc.stdout


def test_replay_settle_does_not_import_geopy():
    proc = _import_and_check('yosoi.core.replay.settle')
    assert proc.returncode == 0, f'settle scaffold leaked geopy: {proc.stdout}\n{proc.stderr}'


def test_replay_models_do_not_import_geopy():
    proc = _import_and_check('yosoi.models.replay')
    assert proc.returncode == 0, f'replay models leaked geopy: {proc.stdout}\n{proc.stderr}'


def test_geocode_module_import_is_also_geopy_free_until_called():
    """Even importing the discovery geocode helper must not eagerly pull geopy.

    The geopy import is guarded inside helper bodies, so module import alone stays
    light; geopy only loads on an actual geocode() call (cache miss).
    """
    proc = _import_and_check('yosoi.core.discovery.geocode')
    assert proc.returncode == 0, f'geocode module eagerly imported geopy: {proc.stdout}\n{proc.stderr}'

# Python SDK delivery

The Python package exposes the public Yosoi SDK concepts through Pydantic
models and typed views. Parsing, providers, extraction, validation, scheduling,
and other processing remain in Rust. Its runtime dependencies are Pydantic and
the packaged native extension.

The release contract is `python/parity/sdk-contract.json`. It accounts for SDK
operations, arguments, data fields, outcomes, and errors. Rust trait mechanics
remain an inventory audit; matching their language-specific signatures is not
a Python feature requirement. CI rejects new unreviewed declarations, changed
signatures or schemas, invalid mappings, and missing or stale capability proof.

Run the gate against an installed wheel:

```sh
python scripts/sdk-parity/run_sdk_parity.py --output-dir .generated/python-parity
```

The command generates the Rust inventory, builds and compares nine fixture
families serially, and writes the full report, frontend summary, execution
identity, ephemeral runtime ledger, and raw results. Reviewed source mappings
are never rewritten by CI. Mapping completeness, capability evidence, and
individual-item evidence are reported separately.

Normal Python 3.12, 3.13, and 3.14.8 wheels pass 282 SDK tests plus one expected
free-threading skip. The 3.14.8t wheel passes all 283 tests, including a fresh
interpreter and synchronized concurrent Contract validation without forcing the
GIL off. The same checks pass for wheels built from the current source archive;
see `COMPATIBILITY.md` for the exact platform and artifact boundary.

Each capability has a runnable example in `python/examples/review.py` and a
public guide under `docs/public/python/`. Hosted CI is configured but is not
part of the local verification claim. Browser certification and additional
wheel platforms are separate from the supported local Linux x86-64 evidence.

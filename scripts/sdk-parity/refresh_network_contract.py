"""Refresh explicit network mappings while retaining every reviewed SDK input.

Requires a completed compiler reference and the matching installed Python wheel.
Writes only on request, after the full denominator and mapping semantics pass.
Existing language-specific reviews and trait policies remain unchanged.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from network_surface_mappings import network_mapping
from refresh_image_contract import run_refresh


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument(
        "--contract", type=Path, default=Path("python/parity/sdk-contract.json")
    )
    parser.add_argument("--write", action="store_true")
    return run_refresh(parser.parse_args(), additional_mapping=network_mapping)


if __name__ == "__main__":
    raise SystemExit(main())

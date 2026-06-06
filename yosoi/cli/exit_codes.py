"""Exit code contract for the yosoi CLI.

Agents and scripts that drive yosoi should branch on these codes:

    0  RECORDS          — extraction succeeded; records emitted on stdout (--json)
    1  ERROR            — unexpected error (fetch failure, bad contract, etc.)
    2  NEEDS_DISCOVERY  — no cached selectors; run `yosoi discover` first
    3  FETCH_FAILED     — URL could not be fetched (network / bot-block)
    4  VALIDATION_FAILED — records fetched but failed contract validation
"""

from __future__ import annotations

RECORDS = 0
ERROR = 1
NEEDS_DISCOVERY = 2
FETCH_FAILED = 3
VALIDATION_FAILED = 4

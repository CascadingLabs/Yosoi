# Action boss-fight manifest

`manifest.py` is the offline, first-slice candidate register for action workloads. It separates the semantic action from the input mechanism and from the evidence required to prove its postcondition.

A0–A4 are auth-free candidates or live-smoke targets. A5 (TodoMVC) is explicitly deferred because keyboard/text input is outside the first slice. No entry performs I/O. There are no action fixtures yet, so no entry claims `frozen`, `selfhost`, pinned freshness, or CI gating.

Public targets are discovery metadata only; they must never gate CI. A future frozen entry must point at a committed, policy-safe fixture and carry pinned freshness before it can enter a deterministic gate.

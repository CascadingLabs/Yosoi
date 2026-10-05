# SDK integration work plan

The intended result is one public Rust SDK, a CLI consuming that SDK, and one
Python package whose Pydantic authoring models delegate processing to Rust.
Existing Rust imports, persisted data, CLI document framing, and public outcome
semantics must remain compatible. The agreed target is normal Python 3.12–3.14
and free-threaded Python 3.14; lower-version packaging is not yet verified.

## Completion requirements

- [ ] Public SDK covers documents, all locator families, policy, typed Contracts,
  Requests, Map, and Search without provider/execution/archive handles.
- [ ] CLI depends on the public SDK and presentation dependencies only; its
  existing commands, document pipe format, and machine output stay compatible.
- [ ] Implementation crates retain their domain boundaries. Browser acquisition
  remains a coarse optional Rust capability, independent of CLI and bindings.
- [ ] Python has ergonomic Pydantic authoring and typed outcomes for the public
  SDK capabilities, including document profiles, parsed reuse, locator plans,
  Contract authoring, policy validation, and async operations.
- [ ] Processing and domain validation stay in Rust. Python converts values and
  models; it does not implement parsers, providers, schedulers, or extraction.
- [ ] Python exceptions, cancellation, ownership, cleanup, and concurrent access
  have meaningful end-to-end checks rather than import-only evidence.
- [x] Normal Python 3.12, 3.13, 3.14 and exact free-threaded 3.14.3 install
  from separate wheels built from an sdist; native imports and operations
  preserve a disabled GIL on the free-threaded interpreter. Local Linux x86-64
  development-profile evidence is recorded in `COMPATIBILITY.md`.
- [ ] Public docs explain package boundaries, capabilities, installation,
  Rust/Python examples, and actual limitations; authored examples are verified.
- [x] Each implemented capability has a runnable public-SDK review example.
  Live examples show actual outcomes; local examples allow repeatable review.
- [ ] Rust downstream/renamed-dependency tests and existing focused regression
  checks pass. Python behavior is checked against Rust using shared fixtures.
- [ ] CI verifies the supported configuration and packaging paths with bounded
  concurrency. Local checks, browser checks, and hosted results are distinguished.

## Current evidence

The Rust facade now exposes Search and the CLI consumes the public SDK. The
focused CLI regressions passed (105 tests without browser features). Documents,
locator plans, policy, parse ownership/reuse, and free-threaded processing have
initial Python checks. Async Requests/Map/Search are implemented and their full
integration verification is ongoing. Pydantic Contract authoring is outstanding.

The compatibility pass subsequently verified all current Python SDK tests on
the four requested interpreter targets, all 28 Python review runs, six Rust
review commands, authored Python documentation snippets, and the public docs
gate. CI now asserts interpreter version and free-threaded ABI selection. These
checks do not close the remaining Contracts/full-parity requirements above.

These gaps are implementation work, not completion exceptions. API reference
coverage and the final handoff must be audited against the resulting source.

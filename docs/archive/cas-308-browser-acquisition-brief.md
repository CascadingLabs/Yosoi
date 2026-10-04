# Future browser acquisition project brief

## Boundary and dependency direction

Build a browser adapter above the existing domain model, `BoundedAcquisitionLifecycle`, `WebCaptureWire`, and `CaptureBundle`. It has **no `wreq` dependency**. It must not import the Direct HTTP resolved spec, pending response, response facts, body decoder, or finalizer. Reuse capture identity, observation accounting/termination, artifact families/capabilities, provenance/lineage, current pre-release v1 canonical metadata, and typed payload bundle validation.

## New browser-only responsibilities

Define a concrete validated `BrowserCaptureSpec` only when implementation begins. It should contain `BrowserCaptureEnvironment` (engine/version, headful/headless mode, viewport/device scale, locale/time zone/color/reduced-motion/user agent, profile/session identity) and truthful capabilities. The adapter owns process/context/page lifecycle, navigation, event interception, settlement and artifact construction:

* source: navigation response representation bytes, distinct from DOM;
* rendered DOM: post-navigation serialization with generation time;
* accessibility: engine snapshot and schema identity;
* network: ordered request/response facts and explicitly chosen intercepted byte layer (wire/content-coded/decoded); never imply unavailable raw wire bytes;
* visual: screenshot pixels plus viewport/scale metadata;
* runtime: bounded console/page-error diagnostics.

Navigation deadline and observation/settlement are separate concepts under one maximum elapsed bound. Specify exact precedence among caller cancellation, browser/process failure, navigation completion, hard deadline and quiet settlement. Cancellation must close owned page/context/process resources and preserve only validated partial evidence. Persistent/incognito profiles and headful/headless modes must be explicit environment facts, not hidden defaults.

## Durable handoff APIs

> **Durable source interpretation:** Browser acquisition reuses the typed `SourceRepresentation` derived-evidence artifact introduced by CAS-324. It must derive from the exact browser-acquired source artifact and preserve bounded declaration, classification, and decoding facts without embedding decoded text or a generic property bag.

A worker returns canonical `WebCaptureWire::to_canonical_json` bytes and copies `CaptureBundle::payloads()` pairs, or transfers ownership via `CaptureBundle::into_parts()`. The receiver parses `WebCapture`, inserts every pair into `CaptureBundle::builder`, and finalizes. No live browser, client, pending response or process handle crosses the boundary.

## Milestones / issues

1. Decide supported engine/version pinning, process ownership, profile isolation, and byte-layer semantics.
2. Add deterministic local browser fixture pages: static, redirects, JS shell mutation, delayed network, navigation failure, infinite activity, accessibility, screenshot and runtime errors.
3. Implement validated browser spec/environment and capability matrix.
4. Implement navigation/cancellation/deadline controller composing bounded lifecycle.
5. Add source, DOM and network collectors; then accessibility, visual and runtime collectors.
6. Assemble provenance/lineage and publish bundle last; add cross-process reconstruction.
7. Add conformance target and resource-leak/process-cleanup checks.

## Acceptance matrix

Each family is tested for requested+retained, requested+unavailable, unrequested, truncation where meaningful, schema/provenance, typed reference, exact bytes/digest, cancellation and deadline. JS-shell fixture proves source differs from rendered DOM. Network fixtures prove declared interception layer. Headful/headless and fresh/persistent-profile facts round-trip. Offline handoff reconstructs identically and tampering fails. Architecture tests prove no wreq/Direct HTTP type dependency.

## Risks and open decisions

Engine protocol stability; reproducible binaries/fonts/rendering; raw-wire unavailability; service workers/cache; redirect attribution; settlement under long polling; screenshot nondeterminism; accessibility schema churn; secret redaction; process cleanup; profile concurrency. Owners: browser project decides engine/protocol, supported modes, byte layers, settlement algorithm and fixture tolerances; model maintainers approve only genuinely shared vocabulary.

## Non-goals

No policy engine, content extraction, crawling, retry scheduler, SDK, remote storage, archive format, query system, or browser implementation in CAS-308.

## CAS-325 physical boundary

Browser specifications, adapter contracts, evidence types, and their contract matrix remain provider-neutral foundation APIs in `yosoi-web-capture`; they are not owned by the Direct HTTP producer. Focused source and test modules are an internal mechanical split and preserve the accepted CAS-330 public exports and semantics.

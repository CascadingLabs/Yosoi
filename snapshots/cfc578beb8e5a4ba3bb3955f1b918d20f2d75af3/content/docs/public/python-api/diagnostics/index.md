---
title: "yosoi.diagnostics"
description: "Public declarations in yosoi.diagnostics."
order: 0
---

`yosoi.diagnostics`

Typed, payload-preserving views of Rust request and projection diagnostics.

[Source: python/yosoi/diagnostics.py:1](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/diagnostics.py#L1-L1)

## Aliases

| Name | Summary |
| --- | --- |
| [`AttemptDiagnostic`](/yosoi/python-api/diagnostics/aliases/attempt-diagnostic/) | Request-attempt diagnostic retaining the original phase or failure detail. |
| [`AttemptFailureKind`](/yosoi/python-api/diagnostics/aliases/attempt-failure-kind/) | Phase that prevented an acquisition attempt from producing its result. |
| [`BrowserFailureReason`](/yosoi/python-api/diagnostics/aliases/browser-failure-reason/) | Typed browser failure category retained alongside operation diagnostics. |
| [`DecodingErrorCode`](/yosoi/python-api/diagnostics/aliases/decoding-error-code/) | Typed decoding failure or unsupported encoding; no successful text is implied. |
| [`Diagnostic`](/yosoi/python-api/diagnostics/aliases/diagnostic/) | Request phase failure, transport detail, or browser failure tagged by kind. |
| [`DirectHttpRedirectErrorKind`](/yosoi/python-api/diagnostics/aliases/direct-http-redirect-error-kind/) | Redirect rejection reason; rejected targets are not followed successfully. |
| [`NotStartedReason`](/yosoi/python-api/diagnostics/aliases/not-started-reason/) | Observed cancellation explaining why a later acquisition never started. |
| [`PartialReason`](/yosoi/python-api/diagnostics/aliases/partial-reason/) | Why a retained representation is partial rather than complete evidence. |
| [`ProjectionReason`](/yosoi/python-api/diagnostics/aliases/projection-reason/) | Typed partial, unavailable, or unprojectable representation explanation. |
| [`SearchAttemptDiagnostic`](/yosoi/python-api/diagnostics/aliases/search-attempt-diagnostic/) | Search-attempt phase diagnostic or structured browser failure category. |
| [`TransportDiagnostic`](/yosoi/python-api/diagnostics/aliases/transport-diagnostic/) | Direct HTTP transport failure or typed redirect rejection details. |
| [`UnavailableReason`](/yosoi/python-api/diagnostics/aliases/unavailable-reason/) | Why requested evidence or its payload is unavailable to projection. |
| [`UnknownReason`](/yosoi/python-api/diagnostics/aliases/unknown-reason/) | Why retained source bytes did not yield a strong format classification. |
| [`UnprojectableReason`](/yosoi/python-api/diagnostics/aliases/unprojectable-reason/) | Why retained source cannot produce the requested document representation. |
| [`WebArtifactFamily`](/yosoi/python-api/diagnostics/aliases/web-artifact-family/) | Captured evidence family; availability and completeness are reported separately. |

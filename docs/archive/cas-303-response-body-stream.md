# CAS-303 response-body stream design

`consume_response_body` is the bounded handoff between a pending Direct HTTP response and later
source classification. It does not perform charset parsing, redirects, archive publication, or
capture finalization.

## Byte domains and precedence

The content-coded counter observes bytes delivered by the HTTP transport up to the configured
bound plus one detection byte and performs a bounded one-byte/EOF probe. Its reported count can
therefore be at most `content_coded_limit + 1` when overflow is proven. The representation bound applies after reversing the declared
`Content-Encoding` chain. Lifecycle events use one domain only: decoded representation bytes
**offered** and the decoded prefix **retained**. Content-coded counts remain separate. This keeps
lifecycle `retained <= admitted`, including high-expansion compressed bodies.

A transport stream error is recorded separately below the decoder and maps to `Disconnect`; an
I/O error created by a content decoder maps to `MalformedCoding`. Provider errors must be sanitized
with `wreq::Error::without_uri` before they become retained sources; debug output and stable
terminals never include a request or response URI. Sink write and commit failures are fatal.
Those fatal states are never replaced by a subsequently observed encoded limit. If encoded and
representation one-over limits become observable in the same read, the encoded limit wins, while
the sink retains no more than the representation bound. Exact limits remain eligible for
`Complete` after the bounded EOF probe.

Cancellation and the original response deadline are selected inside the read loop, so the future
that owns the sink is never dropped by an outer timeout. Cancellation stops at the current body
offset. Deadline selection first calls `observe_through(MaximumElapsed)`, producing lifecycle
`DeadlineReached` rather than a provider interruption. Each accepted prefix is admitted through
the lifecycle before it is written. The offset is derived from the pending response's original
monotonic deadline and configured `MaximumElapsed`, and is clamped to that maximum. The sink is
committed before the final lifecycle stop is selected; therefore commit failure cannot coexist with
a successful controller stop.

## Dependencies

`async-compression = 0.4` is used with default features disabled and exactly `tokio`, `gzip`,
`brotli`, and `zlib`. `GzipDecoder` also supports the HTTP `x-gzip` alias; HTTP `deflate` is decoded
as the zlib-wrapped format. Decoders are composed in reverse header order, as required for stacked
content codings. `tokio-util` adapts the wreq byte stream to `AsyncRead`; `sha2` hashes only the
committed decoded prefix. These dependencies and features are centralized in the workspace
manifest and remain compatible with the workspace Rust 1.98 policy.

# CAS-304 Direct HTTP redirect traversal

## Contract

Direct HTTP is a GET-only executor. The initial request and every automatically followed request use `GET`; this API has no POST method-rewrite semantics. Automatic traversal applies only to HTTP 301, 302, 303, 307, and 308. Responses with 300 or 305, and every other status, remain observable final responses and are not followed.

One absolute monotonic deadline covers the complete attempt and is never restarted between hops. Each admitted redirect records its exact resolved `from`, `to`, and typed HTTP cause. Relative path, query, and fragment references use ordinary URL resolution. The final URL is the current request URL, the redirect vector contains exactly successfully followed transitions, and the resource origin is the final URL's tuple origin. Default policy permits cross-origin HTTP(S); `SameOrigin` compares the target with the initial tuple origin.

Loop identity ignores fragments because fragments are not sent to the network. A redirect to the same scheme/host/port/path/query with a changed fragment is therefore a loop. A changed path or query is a distinct network resource. Hop exhaustion is checked after receiving the redirect response and before resolving or requesting another target.

## Failure and body ownership

Every redirect protocol or policy refusal—hop limit, loop, missing or malformed `Location`, credentials, unsupported scheme, or target policy refusal—stops the lifecycle with secret-safe interruption reason `web_capture.direct_http.redirect_policy`. The last response remains unconsumed and the failure retains the partial `CaptureResolution` ending at the current request URL.

Cancellation and provider request failure stop as caller/provider interruptions. Deadline exhaustion stops as `DeadlineReached`. After any followed hop these failures retain a resolution containing exactly the successful hops and `final_url = current`; they have no later response to preserve.

Redirect bodies are never read, copied, decoded, retried, archived, or admitted as body bytes. When a transition is followed, the response (and therefore its unread body) is dropped before the next GET. When traversal fails while examining a redirect response, that last response and unread body are transferred to the failure. `DirectHttpFailure::into_parts` transfers that response, partial resolution, lifecycle, primary transport error, and any secondary termination-recording failure together; there is no consuming API that discards them. A failure to construct termination evidence or stop the lifecycle is recorded separately and never replaces the primary transport or redirect classification.

On success, `PendingDirectHttpResponse::into_parts` transfers response facts, the complete `CaptureResolution`, lifecycle, and execution identity/deadline-bearing context together with the unread response. Final-response body handling remains the responsibility of the later bounded body stage.

## Secret safety

`Location` and URL values are available only through typed accessors. Failure `Display`, `Debug`, structured summaries, and recursively exposed provider sources do not include request or redirect URIs. Provider errors are retained only after `wreq::Error::without_uri()`.

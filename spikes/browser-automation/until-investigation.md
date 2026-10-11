# Until: deeper review, transport diagnosis, and latency

This investigation preserves `browser-until` at
`6c28a89d1ce1541f24e48140dd7627c95e7bf671`. Its WTF/JJ child workspace is
`/home/andrew/Desktop/cl/yosoi-until-investigation--Yosoi`, bookmark
`until-investigation`. The additions are opt-in diagnostics/tests, not a
production fix. The default workspace was preserved during investigation.
This report was subsequently copied into the default workspace during local
integration of the reviewed SDK, without importing the diagnostic code or
changing production behavior.

The new review found two issues to address before broad release: CSSOM-only
visibility changes can miss the DOM wait's wakeup, and the default 16-event
response watch can become unavailable under unrelated request bursts. The
live navigation failure is separately associated with intermittent asset
failures in the site's serving path, much more frequent over HTTP/2 in the
controlled sample. A longer capture received remote HTTP 503 responses after
30 seconds. No global transport workaround was shipped.

## The Internet navigation

The browser received the main document with HTTP 200 at about 129 ms. CSS and
an image finished around 300 ms, but several scripts received headers only
around 28 seconds and others were still pending at 30 seconds. At the
controller timeout the document was `loading`, with no DOMContentLoaded or
load event and no child frames. This does not show an already-fired load event
being lost by the Until scheduler; Until had not started.

| Probe | Observed result |
| --- | --- |
| Current host main-document GET | HTTP 200, 108 ms; DNS 18 ms, TLS complete 79 ms |
| Same-image bridge main-document GET | HTTP 200, 124 ms; DNS 38 ms, TLS complete 94 ms |
| Same-image parallel HTTP/2 asset GETs | Two of six returned 200 in 193–240 ms; four had no bytes by the 10-second diagnostic deadline |
| Host parallel HTTP/2 asset GETs | One of six returned 200 in 169 ms; five had no bytes by 10 seconds |
| Same-image parallel HTTP/1.1 asset GETs | All six returned 200 in 146–389 ms |
| Normal-CDP Chrome navigation | 30-second failure; still loading |
| Minimal-CDP comparator | Same 30-second failure; still loading |
| Normal Chrome, diagnostic `disable-http2` | Navigation completed in 596 ms; HTTP/1.1 and complete readiness recorded |

The analytics hostname's DNS failure also occurs in the successful HTTP/1.1
run, so it does not explain the initial parser stall. The initial evidence
pointed to an HTTP/2 parallel-resource interaction without identifying the
responsible layer. The fixed-peer and longer captures below substantially
narrow that attribution.

Chromium's [switch definition](https://chromium.googlesource.com/chromium/src/+/HEAD/components/network_session_configurator/common/network_switch_list.h)
documents `disable-http2`. A [Chromium change](https://chromium.googlesource.com/chromium/src/+/d11b055969d2ec2373cfef667f162875ea6e3f1a)
also explains its effect on IP Protection. It was used only as a labeled
diagnostic; sandboxing and site/process isolation remained enabled. It is not
a proposed production default or an automatic retry.

Browser traces: `target/until-navigation-diagnostic-headless/navigation-stages.json`
and `target/until-navigation-http1-headless/http1-navigation.json`. HTTP command
logs are in the shared `/home/andrew/Desktop/cl/Yosoi/target` directory, named
`until-investigation-{host-http2,http1}-parallel.log`. The first same-image H2
probe is retained in the tool transcript; its counts above are not a separate
passing browser result.

### Fixed-peer attribution follow-up (2026-10-10)

The same six static asset paths were fetched with host curl 8.22.0 / nghttp2
1.70.0, with TLS verification enabled. `--resolve` pinned the hostname to
13.248.162.64 or 35.71.177.79, preserving the hostname and TLS SNI. No proxy
environment variables were present; curl reported no proxy use. The TLS
certificate identified `*.herokuapp.com`, issued by Amazon RSA 2048 M01.

Three rounds per peer ran paired HTTP/2 and HTTP/1.1 batches concurrently,
each with six requests and a five-second diagnostic budget:

| Protocol | Requests | HTTP 200 | No response before diagnostic deadline |
| --- | --- | --- | --- |
| HTTP/2 | 36 | 18 | 18 |
| HTTP/1.1 | 36 | 33 | 3 |

These are descriptive counts from a small, correlated sample, not independent
failure probabilities. HTTP/1.1 is not immune. Earlier fresh-connection H2
requests all succeeded, but a later interleaved single-request H2 control also
failed. Thus neither multiplexing nor connection reuse alone is a proven
necessary cause. Both pinned peers had failures in the paired experiment.

A failing six-second HTTP/2 frame capture shows all six request HEADERS sent
successfully, server SETTINGS/ACK received, and two complete HTTP 200 responses
on the same connection in about 0.18 seconds. Four streams received no response
HEADERS. At five seconds, the curl socket had empty send/receive queues,
2,418 bytes sent and 2,419 bytes acknowledged (including TCP sequence overhead),
and about 26 ms RTT. There were no retransmissions reported in that socket
sample. The outgoing requests were not stuck in a local SDK or curl queue;
TCP acknowledgement does not prove the backend application processed them.

The decisive longer capture allowed 35 seconds rather than stopping at the
client's 30-second navigation boundary. On one TLS connection, three assets
returned HTTP 200 in 0.13–0.18 seconds; the other three returned **HTTP 503**
with their first byte at 30.085 seconds, each with 567 response bytes. At
30 seconds all outgoing bytes were acknowledged and the send queue was empty.
Curl exited successfully because receiving HTTP 503 is a completed transport
exchange without `--fail`; the per-request status is the failure evidence.

This confirms a remote HTTP serving failure and explains the navigation
symptom: parser-blocking assets do not arrive before the controller deadline,
so document readiness remains loading and Until never starts. Independent
curl and minimal-CDP reproduction excludes Until's lease/wake scheduling as
the cause of this live navigation stall. There is no evidence here of a general
local outage, DNS failure, TLS failure, or a client that failed to transmit
the requests. A site-specific network interaction cannot be universally
excluded without another network, but it is not needed to explain the observed
remote 503 response.

The specific remote defect remains unconfirmed: app starvation, dyno failure,
or a routing/connection issue require the site's router/application logs.
The 30-second first-byte delay followed by 503 is consistent with Heroku's
[documented request timeout](https://devcenter.heroku.com/articles/http-routing#timeouts),
but does not by itself establish the H12 router error code. Heroku documents
[HTTP/2 termination at its router and HTTP/1.1 forwarding to Common Runtime apps](https://devcenter.heroku.com/articles/http-routing#http-2-considerations);
that architecture is not proof of this site's exact runtime or failing component.
A separate allowlisted response-metadata capture and the first bounded
error-capture attempt succeeded for all six assets. The second attempt received
four HTTP 503 responses at 30.084 seconds, each identifying `server: Heroku` /
`via: 2.0 heroku-router`, with an `Application Error` HTML title and the iframe
`https://www.herokucdn.com/error-pages/application-error.html`. This positively
identifies the remote failures as Heroku application-error responses. It still
does not distinguish an H12 timeout from another internal failure without
router logs. Successful and failing attempts are both retained.

Artifacts under `/home/andrew/Desktop/cl/Yosoi/target/until-network-fixed-peer/`:
`results.json`, `h2_*pair_*.json`, `protocol-peer-pairs.json`, `h2-wire-0.json`,
`h2-wire-long.json`, `h2-error-response.json`, and
`h2-error-capture-{0,1}.json`. The frame logs retain protocol metadata, not raw
headers, cookies, or response bodies. The error-capture artifacts retain only
allowlisted response metadata and the public application-error body; temporary
successful asset bodies were deleted.

Our separate client-side follow-up remains necessary: navigation currently
has a fixed 30-second controller boundary, retains worker capacity while
waiting, and surfaces this as Unknown rather than a useful load-stage report.
That affects policy, scheduling and diagnosis; it did not generate the remote
503. The confirmed CSSOM wake gap and response-watch burst failure below
remain release concerns independent of this website failure.

## Operation overhead

Each row uses 20 alternating paired samples on the same warm 5,241-byte
document and `Visible("#receipt")` condition, with one execution worker.
Timing starts before the public Work call and ends when its receipt returns;
test receipt validation is excluded. Browser startup and navigation are
excluded. Each already-true Until report had exactly one evaluation.

| One-CPU container | Immediate assertion median / p95 | Already-true Until median / p95 | Median paired extra time |
| --- | --- | --- | --- |
| Headless | 2.01 / 2.51 ms | 9.81 / 98.97 ms | 8.00 ms |
| Headful | 1.90 / 2.91 ms | 10.51 / 49.62 ms | 8.33 ms |
| Headless with CPU counters | 1.85 / 73.06 ms | 10.16 / 83.48 ms | 6.44 ms |

These are local microbenchmarks, not service-level guarantees or rankings of
browser modes. In the CPU-counter run, all four long Until samples (69–95 ms)
coincided with cgroup quota throttling. The other sixteen took 6.2–14.5 ms.
This is a correlation across the whole browser/controller cgroup, not a
measurement of precisely how much API time the quota added. Baseline assertions
also had a long tail in that run. Cold Session acquisition was about 2 seconds
in the measured runs; a managed invocation that creates a browser is not a
10-ms operation.

Raw samples and scope: `target/until-latency-headless-corrected/until_latency.json`,
`target/until-latency-headful/until_latency.json`, and
`target/until-latency-cpu-headless/until_latency.json`. The separate
`paired-warm.json` files retain document size and completed paired samples.
An earlier failed harness run remains in `target/until-latency-headless`: it
incorrectly required the waiting Flow to be continuously parked after another
tab's read, even though it can be rechecking a queued hint at that instant.

### Provider components

Twenty samples on a separate tiny 66-byte document measure the underlying
primitives. They exclude Session/Work admission and Flow/report work, and
exclude the first warmup iteration. They are not additive measurements of the
full Until call above.

| Primitive | Median | p95 |
| --- | --- | --- |
| Read document scope | 0.30 ms | 0.59 ms |
| Arm DOM observation watch | 1.58 ms | 2.76 ms |
| Capture rendered DOM with scope checks | 0.84 ms | 63.83 ms |
| Read visibility condition | 0.36 ms | 1.24 ms |
| Acknowledge watch settlement | 1.14 ms | 2.15 ms |

Raw data: `target/until-watch-components-headless/watch-components.json`.

### Pending waits and other-tab progress

Three gated rounds per yield policy and browser mode keep the first tab's
condition false while a second tab requests an observation. With yielding
enabled, the second tab completes before the first tab's gate is opened. With
yielding disabled, it queues behind the retained worker slot and completes
only after that gate opens. Both preserve the exclusive tab leases.

The yielded second-tab reads took 3.8–65.9 ms headless and 3.1–11.9 ms headful.
Gate release to Until completion took 5.1–77.8 ms headless and 6.5–175.8 ms
headful. These latter intervals include local HTTP delivery, wake processing,
worker admission, fresh evidence, and cleanup. Three samples do not establish
a population p95 or isolate pure scheduling latency. Release/reacquisition
and subsequent captures succeeded, and worker counters returned to zero.

## Event-driven scheduling and leases

`Work` retains exclusive control of its tab, plus an operation guard throughout
the compound step. The execution pool limits active browser work; its worker
slots are asynchronous admission permits, not permanent OS threads assigned
to tabs.

The watch is armed before the optional trigger. The trigger runs once and its
receipt is retained. A false check parks on source events, cancellation, or
the deadline. By default the parked Flow releases its worker slot, keeping its
tab ownership. A browser notification makes it eligible to reacquire capacity
for fresh checks. Idle waiting does not poll the browser. A notification is a
hint to read, not evidence that the condition passed.

DOM and AX reads generally do not require bringing the tab forward. Native
input and screenshots share a per-browser foreground/capture lock, so those
operations can serialize even with several worker slots. Current ordinary
Navigate and long browser command calls retain a worker slot while awaiting
their controller future; event-driven yielding is not yet applied to every
kind of I/O wait.

Read-path review found repeated scope reads, a DOM capture and condition
evaluation on each DOM check. AX adds its own tree query; matching JSON response
evidence adds body retrieval. Those are the main browser roundtrips to profile
before optimizing. Remove duplicate work only while preserving scope and
uncertainty guarantees.

Cleanup has its own one-second allowance and still needs pool admission.
Queue saturation can therefore fence an otherwise known trigger if settlement
cannot complete. Cancellation during a browser command or while awaiting the
foreground lock is conservatively unknown; parked cancellation has separately
proved safe settlement and reuse. The current response-byte limit applies
after `Network.getResponseBody` materializes its complete string, so it is not
an end-to-end transport/temporary-memory limit.

## Confirmed edge cases

### CSSOM visibility wakeup gap

An event-gated page applies `CSSStyleSheet.insertRule` to make an existing node
visible without changing its attributes or children. The page acknowledges
the applied rule in 2.5 ms headless / 2.2 ms headful, before the Until deadline
and completion. Until performs one evaluation and then times out in both
modes; the post-wait visibility assertion is true. An otherwise identical
style-attribute mutation wakes the check and satisfies it.

This is a real wake-coverage gap for computed visibility, not an unproven
assumption that the state became true only after the timeout. CSSOM and
pointer-driven styling need appropriate source signals or an explicit,
accurate coverage contract. Add regression assertions before treating this
coverage as implemented; the diagnostic test deliberately records either
Until outcome and can pass while exposing the bug.

Evidence: `target/until-edge-css-ack-{headless,headful}/{cssom_insert_rule,style_attribute}.json`.
Earlier gate-name/channel harness errors are retained separately. No uncertain
action was silently retried.

### Unrelated network burst

The test sets up one click to start a matching fast response and schedule 64
unrelated same-origin fetches.
With the default event capacity 16, Until returns Unavailable/Unknown, preserves
the observed trigger, and fences the Work handle. Capacity 128 completes the
same workload, confirms 64 scheduled fetches, preserves exactly one trigger,
and leaves the Work reusable. The fenced default-capacity case cannot read
back its scheduled-fetch counter; 64 is its configured workload, not a
server-confirmed completion count.
The default result is safe but fragile for busy pages. Filter/coalesce irrelevant
traffic and review capacity defaults; merely increasing a cap is not a proof
of unbounded robustness.

Evidence: `target/until-burst-review-headless/watch-capacity-{16,128}.json`.
The existing fixture's `noise` parameter makes DOM writes; this test explicitly
adds unrelated fetches to exercise network traffic.

### Additional public-site tests

Selenium's public dynamic fixture adds a box and reveals an input after its own
one-second timers. Both native click Until steps satisfy their DOM checks in
headless and headful normal sessions, with one box and retained trigger
receipts. In the httpbin anonymous form case, the submit click is observed;
Until returns Unavailable/Unknown after safe settlement fails and fences the
Work handle. The artifact retains no matching POST response or post-submit
URL/document epoch, so it does not prove that navigation caused this result.
The test establishes conservative failure and fencing, not successful form
submission or a fully attributed navigation-scope transition.

Evidence: `target/until-live-extra-{corrected-headless,headful}/until_live_review.json`
and saved screenshots. Earlier selector mismatch (`type=submit` was absent)
is retained under `target/until-live-extra-headless`.

## Recommended next work

1. Close the computed-visibility wake coverage gap with regression proof and
   explicit source-loss handling. Keep the original scope, one trigger, and
   event-driven waiting contract.
2. Make irrelevant request bursts robust within bounded memory: early filtering,
   fair source draining, and defensible capacity defaults. Preserve uncertainty
   when relevant history is actually lost.
3. Reuse the existing active-navigation handle to park load waits outside worker
   capacity while retaining tab ownership and the effective Flow deadline.
   Preserve full-load behavior unless a readiness policy explicitly selects
   otherwise. Its DCL helper stops remaining loading and is not equivalent.
4. If exact website-internal attribution is needed, obtain its router/application
   logs or corroborate from another network. Fixed-peer captures already show
   remote 503 responses; do not treat HTTP/1.1 as a guaranteed workaround.
5. Consider reducing scope/capture roundtrips after correctness fixes. Add queued
   cancellation, foreground-lock, and saturated-cleanup acceptance tests before
   claiming those states keep the lease reusable.

Production runtime and browser defaults are unchanged. Hosted CI, installed
release artifacts, cross-platform performance, and certified-baseline promotion
are not established by this investigation.

## Local integration after Final Boss review

Andrew requested local integration of the Until SDK after reviewing the
implementation and known limitations. The default workspace now includes the
preserved `browser-until` implementation at `6c28a89d`, plus this report and the
public review page's explicit limitations. The prior default revision
`b774e260` is retained as `browser-until-default-before`. CAS-583 and CAS-584
remain open; local integration is not evidence that either is fixed. CAS-585
remains the separate navigation lifecycle follow-up. No diagnostic runtime
changes or HTTP/2 workaround were imported, and nothing was published.

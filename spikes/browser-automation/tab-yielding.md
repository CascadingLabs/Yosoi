# Retained tabs and yielding workers

This implementation was developed from the default browser-actions integration at
`cbd55918bc4a1e7c5cef45695d749e4c99de5684` in the isolated
`yosoi-tab-yielding--Yosoi` workspace. Its local bookmark is `tab-yielding`.

Andrew approved integration into the default `Yosoi` workspace on October 10.
The integration preserves the newer continuation and JavaScript APIs alongside
the yielding scheduler. The measurements below retain their original isolated
revision provenance; integration does not imply publication or browser certification.

The public example is `crates/yosoi/examples/tab_yielding.rs`. It starts a real
HTTP shipping-quote service with pinned HTMX 2.0.11 and runs typed Flows in regular Stable Chrome.
Every quote checks request identity, service status and the returned amount;
a click, navigation or screenshot alone does not count as business success.

## Measured checkpoint

[Full repeated comparison](tab-yielding-results.md) records 20 policy/scenario
cases, 80 rounds including warmups and 328 confirmed quotes. Under eight-second
I/O, four tabs/one worker finished at warm medians of 20.90 seconds retaining
the worker versus 11.03 seconds yielding. Later-job submission-to-service
medians were 10.30 versus 1.51 seconds. The upstream remained eight seconds;
the gain is batch throughput and admission responsiveness, not raw action speed.

One-tab and short-wait cases had little benefit or overhead/noise. With a
two-slot upstream bottleneck the batch gain shrank to 13.07 versus 12.12 seconds.
Across two browser processes, the explicit shared pool retained its one-worker
limit, while browser/cgroup memory was substantially higher than a one-browser
case. SDK RSS differences were small; do not generalize the noisy browser/cache
memory values into universal increases or decreases.

Six focused live safety cases pass, including same-tab exclusion, another-tab
progress, shared multi-process capacity, queued/resumption deadlines, dropped
wait fencing and a real 32-second wait beyond the old transport default.
Three pool admission tests and three transport tests pass. The unchanged Flow
executor/model/record/assertion checks also pass (7/10/4/4).

Live public-site evidence under `target/yielding-live-sites-final` confirms Rust,
Chrome docs and Qscrape shop readiness with retained DOM and screenshots. Tokio
content assertions pass; its screenshot is honestly rejected because 2,155,035
bytes exceed the 2,097,152-byte artifact bound. A separate Qscrape stateful
checkout run retains a blank shuffled product-grid failure in
`target/yielding-qscrape-checkout`; it is not counted as checkout success and
was not silently retried. These are actual live-site limits/failures, separate
from the controlled batch proof.

The attempted engine lib-test build hit a pre-existing missing `new_search`
reference in unrelated Search tests. The focused execution-pool integration
tests were run instead; no full-suite/hosted CI claim is made. Headful and Python
parity remain unverified. The implementation is integrated locally after review;
no push, publication or browser-promotion claim is made.

## Ownership and execution

```text
ExecutionPool: bounded FIFO worker slots and bounded waiting admissions
    Browser Session A: owned process/context
        Tab A1: exclusive Work lease
        Tab A2: exclusive Work lease
    Browser Session B: owned process/context
        Tab B1: exclusive Work lease
```

The pool can be shared across browser processes. Without an explicit pool,
each Session owns a pool configured by `SessionPolicy.execution_concurrency`
and `maximum_queued_operations` (defaults 2 and 64). Explicit shared pool limits
take precedence over those per-Session creation defaults. Browser process
admission remains separate and currently allows two owned processes.

```rust
let pool = session::ExecutionPool::new(2, 64)?;
let first = session::new().execution_pool(&pool).acquire().await?;
let second = session::new().execution_pool(&pool).acquire().await?;
let lease = first.work().await?;

let outcome = flow::new([
    action::click("#start"),
    action::wait_until(Condition::Visible {
        selector: "#done".into(),
    }, 5_000),
]).with_lease(&lease).invoke().await?;

lease.release().await?;
first.close().await?;
second.close().await?;
```

For one tab, the same Work gate prevents another writer from acquiring it.
Yielding creates no parallel writers on that tab. It frees a worker for other
tabs or other browsers in the shared pool. Concurrent operations on one Work
are rejected by its existing operation guard rather than queued indefinitely.

## Safe parking

1. Acquire execution capacity with cancellation and the original action deadline.
2. Read the current document identity and install a controller-authored observer.
3. Await the installation acknowledgement, then release execution capacity.
4. Wait for the browser promise outside worker capacity, retaining the tab gate.
5. Reacquire capacity, verify document identity and capture confirmation evidence.

The browser observer responds to DOM mutations, load, resize and completed
animation/transition events. It does not poll the page from Rust. A condition
timer is a wait bound; no internal phase restarts the action deadline. Dropping
the wait requests bounded observer/promise cleanup and conservatively fences
that tab after possible dispatch. Unrelated tabs keep working. A deadline while
queued for worker capacity does not dispatch or fence the waiting tab.

Arbitrary JS is not presumed read-only. Input and screenshots continue using
the provider's shared foreground lock. Parking never releases that lock during
an unresolved focus-sensitive operation; the parked DOM observer owns no such
foreground lock. CSS visibility is not a continuous compositor subscription:
intermediate animation frames, arbitrary paint changes and background timer
behavior remain limits to measure, not a promised 10 ms observation interval.

## Reproduce

Build serially with an isolated target directory:

```sh
CARGO_BUILD_JOBS=1 CARGO_TARGET_DIR="$PWD/target" \
  cargo build -p yosoi --features browser --example tab_yielding

spikes/browser-automation/run-yielding.sh \
  "$PWD/target/debug/examples/tab_yielding" "$PWD/target/yielding-comparison" \
  --iterations 3 --case slow-htmx-four-tabs

spikes/browser-automation/run-yielding.sh \
  "$PWD/target/debug/examples/live_tab_flows" "$PWD/target/live-sites" /evidence
```

Set `YOSOI_YIELD_MODE=headful` to use the existing headful Docker compositor.
`--case four-tabs-one-worker` runs a focused comparison. Other cases include
one tab, two/four workers, simultaneous arrivals, zero upstream wait, eight slow
HTMX tabs, a two-slot upstream bottleneck and two browser processes. The service's intentional delay models upstream I/O; test
readiness and controlled completions use events, never sleeps or polling.

`yield_on_wait: false` is the comparison policy: identical observer installation,
but the pending browser promise retains execution capacity. The default is true.
Compare both staged arrivals (new work arrives while an earlier tab waits) and
simultaneous arrivals. Fair interleaving can already start several network jobs
before the first non-yielding wait, so universal linear speedup is not expected.

`comparison.json` records source/browser/image identities, per-browser startup,
one excluded warmup and repeated workflow timings. Memory is sampled every
100 ms: cgroup usage (SDK + browser + cache/kernel), Chrome PSS and SDK RSS.
PSS avoids counting shared browser pages multiple times. Unavailable readings
are null, not zero. These sampled peaks are not exact allocator accounting.
The example saves the last round's receipts and real tab screenshots, outside
the timed interval. Request arrival timestamps come from the HTTP server;
subtract each job's submission timestamp to measure application-level admission
delay (including navigation/setup and controller queues). This is not claimed
to be pure semaphore wait time. Batch throughput is completed jobs per second;
it is not a speedup of an individual click, render or backend calculation.

HTMX's pinned asset is served locally, with the published SHA-384 integrity
`2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg`
verified at download; its Zero-Clause BSD license is stored alongside it.
See [HTMX installation](https://htmx.org/docs/#installing). Live-site Flows remain
separate from the deterministic fixture comparison and retain failed outcomes.

The default runner uses the sandboxed `yosoi-cas383:local` image with regular
Chrome 154.0.8037.57. Google's live Version History on October 10 reports
155.0.8059.39 as current Linux Stable; the experiment's browser is one milestone
behind, within the repository's eligible Stable window. This is new capability
evidence on that exact image, not a full browser promotion/certification.

No distributed scheduler, durable resume, automatic tab-ownership yielding,
Python parity, external-site reliability or release readiness follows from this
experiment. Those remain separate scopes.

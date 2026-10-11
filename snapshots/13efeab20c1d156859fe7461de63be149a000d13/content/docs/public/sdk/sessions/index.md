## Current order and two levels of control

This is the latest agreed direction. The original brainstorming and worked API
sketches below remain design input, not implemented API documentation.

1. **Sessions and the shared browser substrate:** leasing, Work/Watch, the browser
   Request refactor, tab Policy, CDP multiplexing and managed lifecycle. Prove one
   engine serving both ordinary Requests and explicit advanced control.
2. **Actions, Flows and assertions:** a simple scripting facade over the same
   substrate. The engine manages Session acquisition/control/cleanup; advanced
   callers can supply explicit authority.
3. **JavaScript evaluation:** separately enabled execution using those established
   authority, targeting, outcome and capture contracts.
4. **Remove BiDi from current scope:** Firefox is not needed now; focus on CDP.
   This is a scope decision, not a claim that BiDi cannot multiplex.
5. **Archive/replay-grade automation:** preserve actions, Flows, Sessions and
   assertion evidence as inspectable, versioned records. Revisit Alpha's A3Node
   provenance/reuse ideas without importing its runtime wholesale.
6. **Views and Browser Index:** build bounded paginated projections over the
   established live/captured evidence and archive contracts.

Basic captured observations, locator targets and freshness are required by the
earlier steps. They do not require completion of the full paginated Views/Index
project. Step 4 is a scope removal, not an implementation dependency.

The earlier release direction placed archive-grade work in 0.3.0. This sequence
orders the capability roadmap; detailed shaping determines release assignment
and dates for steps 5-6 rather than silently expanding the first 0.2.0 gate.

**Everyday scraping:** Request or Flow gets the job done in a few lines, with
sensible defaults and automatic lifecycle management. **Power users:** the same
operations support explicit Session/resource selection, leases, concurrency,
WatchPolicy and detailed outcomes. Greater authority and visibility must not
require callers to reimplement lifecycle/scheduling or use a different executor.

sessions are how Yosoi interacts and locks browsers safely for stateful actions such as images, screenshots, JS eval, clicking, and of course future agentic harness

the design is more systems than AI or algo or even browser as VoidCrawl handles the underlying calls, sessions is thin locking mechanism w/ rich controls metadata to support the use cases

some user stories might include as thus:

1.) async thread process A creates a browser session to click 3 buttons, async thread process B subscribes (Pub/Sub) to the session Reference to consume the network of said browser session before and after those 3 button clicks
2.) tab scheduling in a session state manner, a process A whiches to hold two session leases, one for tab X and other for Tab Y in browser 1. the process may await interaction/state in either tab, the underlying mutex/Arc for tab scheduling handles the underlying schedule, the session has no idea what tab scheduling is
3.) I wish to keep a tab open for 3 hours then close it at 11:59 UTC
4.) other typical leasing/management usecases of locking that you might expect, TBA
5.) ergonomic hooks to capture screenshots at certain points in the lifecycle of a session (200ms after button is clicked for example) using anonymous functions

pseudo code

kinda rust, kinda python

```rs/py

import ys

Policy:
  browser: headless
  container: true using localhost:<port>
  js_enabled: True


session_A = ys::new::session().bind(&policy).existingTab(&foo)
session_B = ys::new::session().bind(&policy).newtab(&bar)

onClick = ys::BrowserEvent::clickTriggered() or ys::BrowserEvent::DomUpdate()

watchPolicy = defualts()
watcher = ys::Session:watch(&session_A).hook(&onClick).bind(&watchPolicy)

session_A.click().css(h1).first()

res = ys::Session.Work(&session_A).click(ys::css(h1).first()).send().await()?

println!(watcher)
// might need to extract value from watcher derive, but gets event metadata based on watch policy,
// such as screenshot, timing, documents, etc. really whatever it wants and is available from the session.
// not that if a watcher asks for something that the session doesn't expose (for example its in stealth and doesn't expose network documents, or doesn't show AX) then watcher can't get it and will get a typed error (NOT A PANIC!)

// tab scheduling


worker_A = ys::Session.work(session_B).click(h1).send.await // in theory wins first lock (FIFO scheduler)
worker_B = ys::Session.work(session_B).click(h1).send.await


```

## Public Session SDK, then Request integration

Sessions are the public browser access and ownership foundation. Browser
Requests should depend on that same foundation rather than maintain a separate
browser ownership path.

1. Make the Session SDK: expose policy-bound execution ownership and the
   existing lifecycle through `ys::session`, keeping provider handles private.
2. Refactor browser Requests to execute through Sessions. A normal browser
   Request uses an ephemeral session scope; an explicitly bound Request borrows
   the selected existing session/tab. Both use the same underlying machinery.
3. Build ordered work, lifetime controls, events and watchers on that shared
   foundation. Index/views, Actions and JavaScript remain consumers of it.

An ephemeral scope does not require a new browser process. Preserve existing
browser reuse, isolated acquisition and bounded cleanup; expose their ownership
through Sessions instead of implementing them again. Returned Documents remain
captured data and can outlive the session scope.

Requests retain their acquisition/output policy, ordered attempts, cancellation
and response semantics. Session configuration supplies execution authority and
capabilities; it must not silently widen a Request's outputs or permissions.
Closing a borrowed request scope releases its work without closing the caller's
session or tab.

Direct HTTP Requests retain their existing execution path. This browser-specific
refactor does not require a public HTTP Session backend.

## Session, Work and Watch

A Session grants access to browser resources and permitted work. It is an
ownership scope, not itself an atomic action. Session creation may acquire/open
resources without navigating, capturing Documents or executing an action.

Work performs explicit browser operations. Watch requests permitted observation
work and consumes events/evidence. A browser Request packages acquisition Work
and a short-lived Watch with typed output/readiness Policy into a terminal
Response. Observing an already-open page may need only Watch; navigating to a URL
also needs Work and exclusive control.

Collectors produce captured Documents. A Session may expose a live stream/view
of those observations, while each emitted capture retains its own identity and
completeness. Collection stays explicit; an idle Session need not continuously
capture documents. Internal browser pools remain beneath this shared execution
path; a public Session pool is not required for the first slice.

Names and binding syntax remain sketches. The first proof is that existing
Request examples still work through the shared path, and an explicit Session can
serve consecutive Requests without duplicating lifecycle logic. Advanced hooks,
timed lifetime policies and cross-process coordination follow separately.

## Placement-independent browser work

**Design direction, not an implemented API.** The goal is for ordinary callers to
describe the work, required capabilities and lifetime without choosing a CPU,
browser process or host. The execution owner decides where admissible capacity
exists. A caller can still require a particular tab, browser or host when state
or locality matters.

The useful part of the vCPU/serverless analogy is separating requested work from
physical placement. It does not mean a tab is a vCPU or V8 isolate, that tabs have
independent resource budgets, or that live browser state can move freely between
machines. Those properties need separate implementations and measurements.

```text
caller: intent + Policy + placement requirements
  -> execution owner: validate, admit or wait, reserve capacity
    -> Session: a handle to the selected browser resource scope
      -> Work: exclusive control for a declared interaction period
      -> Watch: permitted observation requests and event delivery
        -> existing VoidCrawl/CDP transport and browser runtime
          -> typed receipts and captured Documents
```

The execution owner is a responsibility, not a requirement for a new service or
crate. Initially it runs inside the application and reuses the existing browser
execution manager. A later remote owner can expose the same bounded operations.

### Separate five identities

| Identity                    | Purpose                                                      |
| --------------------------- | ------------------------------------------------------------ |
| Browser instance            | The actual process and its connection/lifecycle owner.       |
| Protocol connection/session | Internal CDP routing; not public Session identity.           |
| Context and tab             | Browser state/isolation scope and the page being controlled. |
| Yosoi Session               | Policy-bound resource access, lifetime and capability scope. |
| Work lease / observation    | Current control authority versus captured evidence identity. |

The initial Session-to-context/tab relationship still needs a public decision.
Whichever shape wins, handles referring to the same tab must share the same
control authority. Opening a second handle must not create a second independent
mutex. Cross-tab operations affecting shared cookies/storage or window focus
need the appropriate broader ownership scope.

### Place first, then preserve state affinity

Placement has hard requirements and optional preferences. The default can mean
"any eligible local capacity" today; it must not silently mean an arbitrary
remote host or availability zone.

Examples of requirements, to shape rather than implement all at once:

- Any fresh eligible context: this task has no pre-existing browser state.
- This existing tab: continue an exact page interaction.
- This context: reuse authentication/storage while opening another tab.
- This browser: satisfy a caller's explicit browser-instance requirement.
- This host or zone: keep work near an input/service or within a chosen boundary.

"Prefer this host" permits placement elsewhere; "require this host" does not.
Unsupported requirements return a typed result instead of being ignored. Policy
answers what is permitted, placement answers where it can run, and admission
answers whether capacity is available within the caller's wait budget.

After acquisition, a retained Session is pinned to the selected live resources.
Placement independence at creation is not transparent migration of cookies,
tabs, document identities or partially completed operations. If its owner dies,
the Session becomes unavailable; recovery needs an explicit later contract.

### One transport owner, one controller, many observers

Start CDP-first. One browser-level connection can route commands through flat
target sessions; independent clients are also supported by Chrome. Protocol
connections are internal capacity choices, not one socket per Yosoi watcher.
See [CDP multi-client support](https://chromedevtools.github.io/devtools-protocol/index.html)
and [flattened target attachment](https://chromedevtools.github.io/devtools-protocol/tot/Target/#method-attachToTarget).

The existing client already correlates pending commands and asynchronous
responses. Preserve that machinery. Do not hold a connection-wide mutex while
awaiting a browser response or page event: the event pump must keep running.

At a controlled tab, the proposed public roles are distinct:

- Work owns the exclusive control lease. It may observe directly without being
  automatically registered as an additional Watch subscriber.
- Watch cannot acquire action authority. Its approved observation requests are
  routed through the owner, and its retained-evidence reads require no action
  lease.
- Collector configuration is coordinated by the owner. One watcher leaving
  must not disable evidence still needed by another consumer.

Watch commands are an explicit capability set, not arbitrary CDP methods that
look like reads. Fresh screenshots/DOM captures consume browser resources and
need capture ordering; arbitrary script evaluation belongs to the separately
enabled JavaScript capability. Watching does not freeze the page or guarantee
that evidence from different moments forms one coherent snapshot.

### Admission, locking and event delivery

These are separate mechanisms even when one owner coordinates them:

1. **Admission** reserves bounded browser/context/tab capacity. Waiters sleep on
   capacity-change notifications with explicit cancellation and deadlines.
2. **Control acquisition** grants one worker a tab or declared broader scope.
   Define whether the lease covers one command or a caller-held interaction
   period; don't accidentally alternate dependent sequences from two workers.
3. **Dispatch** submits approved operations to the existing asynchronous
   transport, preserving correlation and target identity.
4. **Observation delivery** routes events/captures to interested consumers with
   bounded retention and subscriber buffers.
5. **Release** settles or accounts for outstanding work before returning usable
   capacity. Uncertain resources remain unavailable until reconciled.

Start with the existing local scheduler's verified behavior. FIFO may be a
useful local control policy, but it is not automatically a guarantee for all
resource requirements or a future distributed fleet. Avoid busy polling and
avoid holding one tab's lease indefinitely while waiting to acquire another.
Multi-tab jobs need an explicit acquisition order or reservation contract.

A slow Watch subscriber must not stop the browser event pump. State whether a
buffer overflow drops/coalesces observations, disconnects the subscriber or
requires recovery. Report gaps through sequence/capture identities. If a caller
requires lossless recording, provide explicit bounded admission/storage behavior
rather than an unbounded queue.

Lease expiry or caller cancellation does not undo a click or script. Fence old
owners from submitting more work, preserve unknown outcomes after possible
dispatch, and do not transfer control until outstanding work is settled or the
resource is quarantined. State explicitly how canceled acquisition futures and
abandoned handles release ownership.

### Sketch of the ordinary caller experience

The syntax below is illustrative. Session/Request Policy composition, target
types and exact methods must be settled in the docs before implementation.

```rust
// Ordinary code chooses capabilities and intent, not a browser process.
let session = ys::session::new().bind(&policy).acquire().await?;

// A browser Request is the bounded acquisition recipe over this Session.
// The binding must state whether it uses an existing tab or creates a fresh one.
let response = ys::request::new(url)
    .bind(&request_policy)
    .in_session(&session)
    .new_tab()
    .send()
    .await?;

// More explicit automation uses the same underlying ownership/capture path.
let tab = session.existing_tab(tab_id)?;
let work = tab.work().acquire().await?;
let before = work.observe().await?;
let receipt = work.click(target_from(&before)?).send().await?;
let after = work.observe().await?;
work.release().await?;

session.close().await?;
```

A Watch path can be separate from its worker. This example requires network
collection to be permitted and supported; it is not a claim of current network
Document availability. Registration must acknowledge that collection is armed
before the triggering work begins.

```rust
let watcher = tab.watch().bind(&watch_policy).subscribe().await?;
let work = tab.work().acquire().await?;
let receipt = work.click(target).send().await?;
let evidence = watcher.next_for(receipt.operation_id()).await?;
work.release().await?;
watcher.close().await?;
```

Operation IDs identify the requested evidence window; they do not prove that
every network event in that window was caused by that operation. Session
capabilities bound WatchPolicy. Unsupported requests return typed errors and
never widen the Session's collection permissions.

### Actual implementation path

| Phase                               | Change                                                                                                                           | Completion proof                                                                                                                          |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Public Session SDK               | Expose existing ownership/lifecycle through a small typed Session contract. Define owned/borrowed resources and Policy.          | Explicit acquire/close and cancellation are inspectable; provider handles stay private.                                                   |
| 2. Browser Request migration        | Route normal ephemeral and explicitly bound browser Requests through the same Session machinery. Keep Direct HTTP unchanged.     | Existing Request outcomes/examples remain compatible; explicit reuse works; no duplicate launch/admission/capture/cleanup implementation. |
| 3. Work and Watch                   | Add the approved control lease and bounded observer capabilities over that shared path.                                          | One worker and two watchers function concurrently; capture ordering, cancellation, slow readers and cleanup are verified.                 |
| 4. Actions / Flows, then JavaScript | Build atomic actions, managed sequential Flows and typed assertions; JavaScript follows. Full paginated Views/Index comes later. | Simple and advanced Rust/Python workflows share execution; failure evidence and default-denied JS behavior are verified.                  |
| 5. Local capacity/placement         | Expose only the capacity and affinity controls required by concrete multi-tab workflows. Reuse internal browser pooling.         | Saturation waits through events, pending work is bounded and state-affinity requirements are honored.                                     |
| Later: remote/distributed ownership | Introduce an explicit remote execution owner and placement across hosts when local semantics are proven.                         | Owner loss, transport loss, fencing and ambiguous side effects have measured, documented recovery behavior.                               |

Phases 1-4 are the core 0.2.0 direction. Basic capacity safety is required from
the beginning; a public fleet/pool API and distributed placement are later
capabilities, not release prerequisites. BiDi is removed from current scope.

Begin with a narrow source inventory: current public Request -> yosoi-engine
RequestExecutor -> existing browser runtime/provider. Identify which current
owners can be shared or moved into the Session boundary. RequestExecutor's
adapter configuration alone is not browser lifetime ownership. Avoid wrapping
it in a Session name without making resource lifetime and control real.

For remote execution, an Arc is not a cross-process reference and an anonymous
Rust/Python closure is not automatically a transferable task. Later remote
workers need serialized bounded commands, opaque Session/lease IDs, authority
checks and an owning executor that enforces lease generations. Commands already
dispatched to a browser may outlive a disconnect; do not automatically replay
them on another host. Local callback hooks remain local until a separate remote
hook contract exists.

### First experiment before broad scheduling

Use one regular Stable browser, two isolated contexts/tabs and one internal CDP
owner. Submit control from two callers to the same tab and verify that only one
lease is active. Attach two approved watchers, perform a navigation/interaction,
and check response/event correlation. Delay one consumer, cancel a waiter and
disconnect one watcher; the other work must continue with bounded resources and
explicit evidence gaps where applicable.

Compare a shared connection with an independent observer connection only if a
specific requirement needs it. Record latency, pending commands, retained bytes
and cleanup; do not infer a capacity of hundreds of sessions from protocol
support alone. This experiment proves the ownership/event model first. A large
machine or multiple hosts then increases capacity behind the same caller
contract instead of changing how browser work is authored.

## Worked SDK sketches

**All APIs below are proposals, not runnable examples of today's SDK.** These
examples explore caller experience before choosing exact Rust/Python types.
Adjacent examples are alternatives where noted. `?` assumes an async function
returning an appropriate Result; Python examples assume an async function.
Production examples will be compiled/run once the contracts are implemented.

### 1. The smallest browser Request

The familiar Request call remains small. Browser acquisition uses an ephemeral
Session scope internally; callers need not construct a runtime or lease.

```rust
let mut policy = Policy::default();
policy.request.acquisition = Acquisition::Browser;

let response = ys::request::new("https://example.com")
    .bind(&policy)
    .send()
    .await?;

// The Session work scope has finished; captured Documents remain usable.
let document = response.document(DocumentKind::RenderedDom)?;
let links = document.locate(&link_plan)?;
```

```python
policy = ys.Policy()
policy.request.acquisition = ys.Acquisition.BROWSER

response = await ys.request.new("https://example.com").bind(policy).send()
document = response.document(ys.DocumentKind.RENDERED_DOM)
links = document.locate(link_plan)
```

`Acquisition::Browser` is proposed shorthand; the migration must preserve
existing acquisition/output authoring rather than require this spelling.

### 2. Explicit Session: acquire once, perform several Requests

This sketch makes the ownership visible while retaining the same Request
implementation. Requests create fresh tabs in this Session's chosen context;
whether state is shared is an explicit Session configuration decision.

```rust
let session = ys::session::new().bind(&policy).acquire().await?;

let result = async {
    let first = ys::request::new("https://example.com/catalog")
        .bind(&policy)
        .in_session(&session)
        .new_tab()
        .send()
        .await?;

    let second = ys::request::new("https://example.com/prices")
        .bind(&policy)
        .in_session(&session)
        .new_tab()
        .send()
        .await?;

    Ok::<_, SessionError>((first, second))
}.await;

// Attempt explicit close on both success and operation error.
let cleanup = session.close().await;
let (first, second) = finish_with_cleanup(result, cleanup)?;
```

`finish_with_cleanup` stands for the proposed common outcome helper: preserve
both the primary failure and any cleanup failure. Error conversion and this
helper's final type are shaping decisions, not an existing SDK facility.

```python
async with ys.session.new().bind(policy).acquire() as session:
    first = await (
        ys.request.new("https://example.com/catalog")
        .bind(policy).in_session(session).new_tab().send()
    )
    second = await (
        ys.request.new("https://example.com/prices")
        .bind(policy).in_session(session).new_tab().send()
    )

# Exiting releases owned resources; first/second retain captured data.
```

The async context manager must preserve operation and cleanup failures. Rust
Drop can arrange best-effort cleanup; explicit async close remains the path for
verified teardown.

### 3. Local browser configuration

Policy is ordinary authored data; the default is headless, supported typed
actions allowed, JavaScript off and DOM observation enabled.

```rust
let mut policy = Policy::default();
policy.session.browser = Browser::Local {
    mode: BrowserMode::Headful,
};
policy.session.allowed_actions = AllowedActions::Only(vec![
    ActionKind::Navigate,
    ActionKind::Click,
    ActionKind::EnterText,
]);
policy.session.allow_arbitrary_js = false;

let session = ys::session::new().bind(&policy).acquire().await?;
```

### 4. Explicit remote browser and borrowed lifetime

Remote launch mode belongs to the browser host. Attaching to a connection does
not grant permission to close the host browser or unrelated tabs.

```rust
policy.session.browser = Browser::Remote {
    endpoint: BrowserEndpoint::Cdp {
        url: "ws://browser-a:9222/devtools/browser/<browser-id>".parse()?,
    },
    ownership: RemoteOwnership::BorrowBrowser,
};

let session = ys::session::new().bind(&policy).acquire().await?;
let tab = session.new_tab().await?; // explicitly owned by this scope

// Close resources created here and detach; don't terminate browser-a.
session.close().await?;
```

```python
policy.session.browser = ys.RemoteBrowser(
    endpoint=ys.CdpEndpoint(url=browser_websocket_url),
    ownership=ys.RemoteOwnership.BORROW_BROWSER,
)

async with ys.session.new().bind(policy).acquire() as session:
    tab = await session.new_tab()
```

`BorrowBrowser` alone does not settle context isolation; an explicit context
selection/creation contract is still required. Endpoint resolution and
connection credentials remain separate typed configuration.

### 5. AX observation without retaining DOM

```rust
policy.session.modalities = Modalities {
    dom: None,
    ax: Some(AxPolicy::default()),
    network: None,
    visual: None,
};

let session = ys::session::new().bind(&policy).acquire().await?;
let tab = session.new_tab().await?;
let work = tab.work().acquire().await?;

let observed = work.observe().await?;
let ax = observed.ax()?;
let dom_result = observed.dom(); // typed unavailable result
work.release().await?;
```

Choosing AX does not imply that every provider supplies it. Unsupported
configuration must be reported at the documented validation/admission boundary.

### 6. Hold control across a dependent interaction

Acquire one Work lease for the sequence. Ordinary calls within it do not
reacquire the same mutex, preventing accidental self-deadlock.

```rust
let work = tab.work().acquire().await?;

let result = async {
    let before = work.observe().await?;
    let input = before.targets().named("Search")?.require_unique()?;
    work.enter_text(input, "public energy reports").send().await?;

    // Resolve from fresh evidence after changing the page.
    let current = work.observe().await?;
    let submit = current.targets().named("Submit")?.require_unique()?;
    let receipt = work.click(submit).send().await?;
    let after = work.observe().await?;

    Ok::<_, SessionError>((receipt, after))
}.await;

let cleanup = work.release().await;
let (receipt, after) = finish_with_cleanup(result, cleanup)?;
```

```python
async with tab.work().acquire() as work:
    before = await work.observe()
    target = before.targets.named("Search").require_unique()
    await work.enter_text(target, "public energy reports").send()

    current = await work.observe()
    submit = current.targets.named("Submit").require_unique()
    receipt = await work.click(submit).send()
    after = await work.observe()
```

This example does not require a paginated view. Exact name lookup is only a
candidate targeting convenience; ambiguity and missing targets are typed
outcomes rather than implicit `.first()` selection.

### 7. Request acquisition inside an already held Work lease

Do not implicitly reacquire control when a caller already holds it. This is an
alternative binding form to shape alongside `.in_session().existing_tab()`.

```rust
let work = tab.work().acquire().await?;

let response = ys::request::new("https://example.com/account")
    .bind(&request_policy)
    .with_work(&work)
    .send()
    .await?;

// Request released its observation scope, not our Work lease or tab.
let observation = work.observe().await?;
work.release().await?;
```

A retained session's operation policy cannot be widened by RequestPolicy.
Session lifetime, Work ownership and Request acquisition timeout are distinct.

### 8. One worker, two watchers

Watch registration arms permitted collectors before work begins. The worker can
observe directly and is not automatically counted as a third subscriber.

```rust
let network_watch = tab.watch()
    .bind(&network_watch_policy)
    .subscribe().await?;
let visual_watch = tab.watch()
    .bind(&visual_watch_policy)
    .subscribe().await?;

let work = tab.work().acquire().await?;
let receipt = work.navigate(url).send().await?;

let network = network_watch.next_for(receipt.operation_id()).await?;
let visual = visual_watch.next_for(receipt.operation_id()).await?;

work.release().await?;
network_watch.close().await?;
visual_watch.close().await?;
```

```python
async with tab.watch().bind(network_policy).subscribe() as network:
    async with tab.watch().bind(visual_policy).subscribe() as visual:
        async with tab.work().acquire() as work:
            receipt = await work.navigate(url).send()
            network_evidence, visual_evidence = await asyncio.gather(
                network.next_for(receipt.operation_id),
                visual.next_for(receipt.operation_id),
            )
```

Both WatchPolicies must fit the Session capabilities and provider support. Each
wait needs a defined completion condition, deadline and cancellation semantics;
`next_for` must not wait forever for evidence that cannot occur. Operation
correlation does not prove causation of every event.

### 9. Hook a screenshot to an operation event

Prefer a typed capture plan for common hooks. Local callbacks consume resulting
evidence; they do not receive unrestricted browser control.

```rust
let mut watch_policy = WatchPolicy::default();
watch_policy.trigger = Trigger::After {
    event: EventKind::ActionDispatched(ActionKind::Click),
    delay: Duration::from_millis(200),
};
watch_policy.capture = CaptureSelection::Screenshot;
watch_policy.deadline = Duration::from_secs(2);

let watcher = tab.watch()
    .bind(&watch_policy)
    .on_capture(|capture| {
        // Bounded local callback; no tab/controller handle.
        tracing::info!(capture_id = %capture.id(), "screenshot captured");
    })
    .subscribe().await?;
```

The delay is an explicit requested capture time, not a readiness sleep. The
receipt records trigger time, scheduled time and actual capture time. It must
say if queueing, navigation or lease coordination prevented the requested
capture. Slow callbacks run outside the browser event pump under bounded policy.

### 10. View pagination stays on its capture

```rust
let observed = work.observe().await?;
let view = observed.view(View::Index { page_size: 40 });

let first = view.first_page()?;
let second = match first.next_cursor() {
    Some(cursor) => Some(view.page(cursor)?),
    None => None,
};

let target = first.target(reference)?;
let receipt = work.click(target).send().await?;
let newer = work.observe().await?;

// view still exposes observed, not newer. Live action validation is separate.
let old_first = view.first_page()?;
```

Retention bounds decide how long a capture/view remains available. Expiration
must be explicit; old cursors cannot silently resolve against a replacement.

### 11. Explicit JavaScript authority

```rust
policy.session.allow_arbitrary_js = true; // default is false

let work = tab.work().acquire().await?;
let receipt = work.javascript(Javascript {
    source: "({ title: document.title, url: location.href })".into(),
    arguments: vec![],
    frame: FrameSelection::Main,
    limits: JavascriptLimits::default(),
}).send().await?;

let value = receipt.result()?;
work.release().await?;
```

The tab in this example must be acquired under the explicitly enabled Policy;
editing a policy variable after acquisition cannot retroactively grant a live
session permission. The example is still arbitrary JavaScript, even if its
source appears read-only. Script errors/timeouts can follow partial mutation.

### 12. Waiting for capacity is cancelable and bounded

```rust
let cancellation = CancellationToken::new();

let session = ys::session::new()
    .bind(&policy)
    .wait(WaitPolicy {
        maximum: Duration::from_secs(5),
        pending: PendingBehavior::RejectWhenFull,
    })
    .acquire_cancellable(&cancellation)
    .await?;
```

```python
try:
    async with asyncio.timeout(5):
        session = await ys.session.new().bind(policy).acquire()
except TimeoutError:
    # Acquisition cancellation must reclaim any partial reservation.
    session = None
```

The execution owner wakes waiters on capacity changes. No caller-side polling
loop is needed. Acquisition timeout and operation timeout have different outcomes:
capacity was never granted versus an operation may already have been dispatched.

### 13. Preserve unknown action outcomes

```rust
match receipt.execution() {
    ExecutionOutcome::Rejected(reason) => report_rejection(reason),
    ExecutionOutcome::Observed { evidence, .. } => inspect(evidence),
    ExecutionOutcome::Unknown { operation_id, reason } => {
        record_uncertainty(operation_id, reason);
        // Reconcile current state if the Session remains usable.
        // Do not automatically click/submit again.
    }
}
```

This is a proposed outcome shape; the final model must retain dispatch facts as
well as observed effects. Observed execution is not automatically business-goal
success. Transport loss cannot be hidden by moving the same action to another
browser.

### 14. Two tabs: parallel independent work

```rust
let tab_a = session.new_tab().await?;
let tab_b = session.new_tab().await?;

let (result_a, result_b) = tokio::join!(
    acquire_capture_release(&tab_a, url_a),
    acquire_capture_release(&tab_b, url_b),
);

// Both futures complete, including their cleanup paths, before collecting errors.
let response_a = result_a?;
let response_b = result_b?;
```

`acquire_capture_release` represents a small application helper over the shared
Session/Request path, not another execution engine. Same-context tabs may share
storage. Separate contexts are required where independent state is needed.

For a job that must hold both tabs at once, shape an explicit combined
reservation/ordered acquisition contract. Acquiring A, waiting indefinitely for
B, while another job holds B and waits for A is not acceptable.

### 15. Placement requirements without revealing physical resources

**Future placement sketch; not a 0.2.0 fleet requirement.** Start with local
capacity. Add remote host/zone requirements only when an execution owner can
actually enforce them.

```rust
// Any eligible local capacity; no specific browser state required.
let session = ys::session::new()
    .bind(&policy)
    .placement(Placement::LocalAny)
    .acquire().await?;

// Require existing state. Failure is preferable to silently using another tab.
let pinned = ys::session::new()
    .bind(&policy)
    .placement(Placement::ExistingTab(tab_identity))
    .acquire().await?;

// Later: strict locality plus a preference among eligible placements.
let future_session = ys::session::new()
    .bind(&policy)
    .placement(PlacementRequirements {
        require_zone: Some("zone-a".into()),
        prefer_host: Some("browser-host-07".into()),
    })
    .acquire().await?;
```

The task sees a Session handle after placement. It does not see a CPU number,
socket or CDP session ID. The acquired Session stays pinned to its live resources;
retained state does not transparently migrate when a preference changes.

### 16. Session lifetime and scheduled owned-tab close

**Later lifetime sketch.** Ownership and the behavior at expiry must be explicit.
Do not conflate release of control with closing a borrowed tab/browser.

```rust
let lifetime = SessionLifetime {
    maximum: Some(Duration::from_secs(3 * 60 * 60)),
    close_at: Some(parse_utc("2026-10-05T23:59:00Z")?),
    expiry: ExpiryAction::CloseOwnedResources,
};

let session = ys::session::new()
    .bind(&policy)
    .lifetime(lifetime)
    .acquire().await?;
```

The first applicable deadline initiates documented teardown. In-flight actions
must be accounted for, and their side effects are not undone. `close_at` is not a
promise that resource disposal can finish at exactly that instant.

### What these examples are testing in the design

- Ordinary browser Request stays ergonomic while using the shared Session path.
- Explicit ownership is available without exposing protocol machinery.
- Worker and Watcher are separate public roles; observation is allowed within
  Work without automatic Watch registration.
- Request inside held Work cannot reacquire its own lock.
- Watch permissions, arming, deadlines and backpressure are explicit.
- Placement requirements constrain acquisition; they do not erase live-state
  affinity or promise remote migration.
- Cancellation, expiry and close preserve ownership and unknown outcomes.
- Rust/Python examples express the same model, with language-native cleanup.

## Simple Actions, Flows and assertions

These are additional API sketches, not a second engine. A managed Flow composes
atomic actions, observation work and checks over the Session substrate. Ordinary
scripts need not acquire tabs, configure pools or release leases explicitly.

```rust
let flow = ys::flow::new([
    ys::action::navigate("https://example.com"),
    ys::action::wait(100), // deliberate pause, milliseconds
    ys::action::click("h1"),
    ys::action::screenshot(),
]);

let outcome = flow.bind(&browser_policy).invoke().await?;
```

Custom Policy adds control without changing the execution model:

```rust
let outcome = flow.bind(&policy).invoke().await?;
```

The engine acquires suitable capacity, navigates, holds control across dependent
steps, resolves each locator against current state, records outcomes/captures
and cleans up owned resources. Define missing/ambiguous target behavior; don't
hide `.first()` selection inside click. Captures outlive managed teardown.

```rust
let flow = ys::flow::new([
    ys::action::navigate("https://example.com"),
    ys::action::wait_until(
        ys::flow::Condition::Visible { selector: "#search".into() },
        5_000,
    ),
    ys::action::enter_text("#search", "energy reports"),
    ys::action::click("button[type=submit]"),
    ys::action::wait_until(
        ys::flow::Condition::Exists { selector: ".result".into() },
        5_000,
    ),
    ys::action::assert(ys::flow::Condition::CountAtLeast {
        selector: ".result".into(), count: 1,
    })
    .into(),
    ys::action::screenshot(),
]);
```

```python
flow = ys.Flow([
    ys.wait_until(ys.css("#search").is_visible()).timeout_ms(5_000),
    ys.enter_text(ys.css("#search"), "energy reports"),
    ys.click(ys.css("button[type=submit]")),
    ys.wait_until(ys.css(".result").exists()).timeout_ms(5_000),
    ys.assert_that(ys.css(".result").count().at_least(1)),
    ys.screenshot(),
])

# Proposed Python API; the Rust core is the implemented completion gate.
outcome = await flow.bind(browser_policy).invoke()
```

Python cannot use `assert` as a normal method/function name; `assert_that` is a
candidate language-native spelling. Rust `ys::action::assert(...)` is an SDK operation,
not `assert!`: a failed check returns expected/observed facts and evidence,
never a panic. Assert checks once; wait_until waits within its explicit deadline.

The default Flow retains failed actions/assertions and local cancellations, then
continues when safe. Policy, Flows and individual steps can override failure and
cancellation independently with `Continue`, `Stop(CurrentFlow)` or
`Stop(Invocation)`; see the [continuation contract](../../browser-automation-review/continuation.md).
Root/Session cancellation still stops descendants. Cancellation is not rollback.
A timeout after possible dispatch stays unknown and fences unsafe reuse rather
than causing automatic replay. Configure failure capture explicitly rather than
assuming every failed step can produce a screenshot.

Advanced binding is the same runner with caller-owned authority:

```rust
let work = tab.work().acquire().await?;
let outcome = flow
    .bind(&policy)
    .with_lease(&work)
    .invoke()
    .await?;
work.release().await?;
```

This advanced form does not navigate to a new starting URL unless the Flow
explicitly contains navigation. It cannot widen existing Session permissions or
reacquire a Work lease already held by the caller. Cleanup-error handling follows
the common Session outcome contract.

## Archive/replay grade and Alpha A3Node continuity

Step 5 builds on the actual Session/action/Flow/assertion contracts. Preserve
the useful A3Node principle: evidence-backed references and provenance are
primary; selectors/fingerprints are derived claims that require verification.
The historical design sources are
[Provenance-first rendered field](https://linear.app/cascadinglabs/document/provenance-first-rendered-field-pruning-as-the-a3-substrate-b2e9f168c3e1)
and [QA Index Beachhead](https://linear.app/cascadinglabs/document/qa-index-beachhead-strategic-architecture-and-beta-path-cadaa2d488be).
These are design input, not proof of current implementation or a request to
restore Alpha wholesale.

The candidate durable unit is:

```text
Flow definition + schema/version + effective Policy
  + Session/resource/provider identity and declared capabilities
  + ordered operation receipts and parent/transition relationships
  + captured canonical evidence and exact references
  + assertion expected/observed results and verification evidence
```

Distinguish two replay experiences:

- **Offline evidence replay:** reconstruct archived observations and reevaluate
  supported locators/assertions over retained evidence without browser/network
  access. Return unavailable for checks requiring uncaptured live state.
- **Live Flow rerun:** acquire new authority, execute against current browser
  state, revalidate targets and record new receipts. Historical evidence or a
  fingerprint match does not authorize side effects or guarantee the same result.

Capture/view refs remain snapshot-local unless a stronger cross-state identity
contract is proven. Fingerprints may propose reuse; fresh evidence, Policy and
verification decide. Partial recordings, unsupported modalities, unknown action
outcomes and assertion failures remain inspectable rather than being rewritten
as successful replay.

Durability shaping includes canonical identities, integrity, schema evolution,
atomic persistence, retention/sensitivity and reconstruction. It does not claim
that a complete live browser or host can be restored from a Session record.

Step 6 then derives the bounded Views/Browser Index from these evidence contracts.
Views can be rebuilt; they must not become the only surviving source of truth.

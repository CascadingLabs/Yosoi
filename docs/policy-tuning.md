# Policy tuning: the first SDK story

## User story

I run Yosoi inside an application that may perform several independent
operations at once. I want one Policy declaration to describe the execution
tuning I choose, then bind that same Policy to Requests, Documents, and future
Map, Search, and Crawl operations. Later I can favor memory use, CPU use, or
latency by changing the Policy value without changing the operation's query.

Today I can set `policy.tuning` to `Tuning::default()`, or use
`Policy::default()` and receive the same behavior. The bound value follows a
Request into its prepared Policy snapshot and a parsed Document into later
location. Tuning is part of Policy, with no separate operation override.

The same offline flow is compiled as
[`crates/yosoi/examples/policy_tuning.rs`](../crates/yosoi/examples/policy_tuning.rs).

The same Policy is bound across current operations:

```text
let policy = Policy { tuning: Tuning::default(), ..Policy::default() };
request::new(target).bind(&policy).prepare()
document.bind(&policy).locate(&plan)
let parsed = document.bind(&policy).parse()?;
parsed.locate(&plan)
```

The linked offline example compiles and exercises these paths without network
access.

Binding borrows the caller's Policy without mutating it. Request preparation
snapshots the complete selected Policy, including tuning. Unbound operations
use `Policy::default().tuning`.

## What the default does now

There is one mode: `Default`. It preserves the installed package's current
execution choices. It does not change acquisition kind, set worker count,
throttle CPU, promise a memory ceiling, or add a new resource failure.

Source HTML **already has private streaming evaluation** in the default
workspace. One-shot `Document::locate` first tries that exact, certified path.
When its proof is incomplete, it parses the retained HTML5 tree and evaluates
there. `Document::parse` constructs the reusable representation directly for
multiple locations. `Tuning::default()` leaves these routes unchanged. This is
evaluation over bytes already owned by `Document`, not network input streaming.

The existing typed input, node, depth, selector-work, match, and output limits
remain separate safety constraints. Tuning is an execution preference for
future measured modes. Different operations may select different tuning values
in one host process; their threads and heap are shared, so a choice cannot
promise independent per-thread memory use.

## Identity and later modes

Default tuning is omitted from canonical Policy JSON and the effective-policy
identity projection. Previously archived default Policy values still decode to
`Tuning::default()` and retain their exact identity. The in-memory effective
Policy and prepared Request expose that selected value.

Before adding a mode with different execution behavior, define its CPU and
memory target meaning, worker and buffer ownership, backpressure behavior,
observability, and identity version. The mode must preserve result semantics;
benchmark evidence should show where it helps and where it does not. New SDK
operation builders should borrow Policy through `.bind(&policy)` and snapshot
its tuning value at preparation or execution, as Requests does here.

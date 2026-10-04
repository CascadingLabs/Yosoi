# Policy declarations and snapshots

Status: current policy values are passive data. No Yosoi runtime binding or
process-level policy carrier is defined here.

## Authoring and attempt snapshots

    use yosoi::prelude as ys;

    let page_policy = ys::policy::Page {
        acquisition: ys::policy::Acquisition::DirectHttp,
        optional_evidence: vec![],
    };
    let request_policy = ys::policy::Request::default();
    let policy = ys::Policy {
        page: page_policy,
        request: request_policy,
    };

    let snapshot = ys::PolicySnapshot::from_policy(&policy)?;
    let prepared = ys::PolicyResolver::resolve(&snapshot, request, context)?;
    let capture = prepared.execute(&cancellation).await?;

Policy is an ordinary value that applications can retain, inspect, clone, or
validate. PolicySnapshot::from_policy borrows the declaration, validates and
identifies it, then owns an immutable clone. The declaration remains with its
caller.

The pure resolver borrows the snapshot and prepares one attempt. The prepared
attempt owns the exact validated capture spec and its AppliedPolicy facts;
execution consumes that spec without rereading a declaration or ambient
configuration.

## Runtime ownership

The Yosoi facade currently exposes policy values, resolution inputs, prepared
attempts, and capture execution. It does not contain a Yosoi runtime object,
Policy::bind, a PolicyTarget bridge, or a process-wide policy setting.
Applications that keep a declaration or snapshot for their process own that
lifetime themselves.

PolicySnapshot exposes only a borrowed Policy and its effective identity. A
per-capture resolver call does not mutate the declaration or snapshot. There
are no policy layers, chaining, or per-call policy overrides.

Requests now owns the operation boundary: an unbound request snapshots
`Policy::default()` inside `send`, while `request.bind(&policy)` borrows one
complete caller-owned declaration and snapshots it for that send. `send_with`
reuses execution contexts, not policy state. There is still no long-lived
process policy registry, replacement API, merge, or implicit mutable setting.

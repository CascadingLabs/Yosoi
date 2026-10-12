---
title: 'Keep evidence after the browser closes'
description: '0.2.0 concept review. Rust examples describe the local spike; Python examples are proposals.'
order: 6
---

# Keep evidence after the browser closes

Archive stores versioned records, operation receipts and captured evidence.
You can reopen them later without launching Chrome.

## Save a Flow outcome

`outcome` below is a FlowOutcome returned by a completed attempt, which may
have succeeded, failed or stopped with an unknown result.

```rust
use yosoi::Archive;
use yosoi::automation_record::AutomationRecord;

let record = AutomationRecord::new(
    yosoi::session::new_operation_id(),
    Vec::new(), // Extra observations, outside the Flow.
    Vec::new(), // Extra receipts, outside the Flow.
)?
.with_flow_outcome(outcome)?;

let archive = Archive::open("./automation-archive").await?;
let reference = record.write_to(&archive).await?;

// Persist this reference so another process can find the same record.
let reference_json = serde_json::to_string(&reference)?;
```

The Flow outcome retains its steps and observations. This minimal example
omits the optional AutomationContext. The integrated spike separately records
effective policy identity, Session settings, provider/browser metadata and
parent lineage. Metadata supplied by a harness is not automatic source attestation.

## Reopen in another process

```rust
use yosoi::automation_record::AutomationRecordRef;

let reference: AutomationRecordRef = serde_json::from_str(&reference_json)?;
let archive = Archive::open("./automation-archive").await?;
let record = AutomationRecord::read_from(&archive, &reference).await?;

println!("{}", record.id());
```

The reference must point to the same Archive's stored payload. Missing or
tampered payloads return errors. Records are capped at 64 MiB.

## Check the saved DOM

```rust
use yosoi::flow::Condition;
use yosoi::view::View;

let flow = record.flow_outcome()
    .ok_or_else(|| std::io::Error::other("missing Flow outcome"))?;
let observation = flow.steps.iter()
    .filter_map(|step| step.receipt.observation.as_ref())
    .find(|observation| observation.html.is_some())
    .ok_or_else(|| std::io::Error::other("missing DOM capture"))?;

let view = View::from_observation(observation, 10)?;
let passes = view.verify_condition(observation, &Condition::CountAtLeast {
    selector: ".row".into(),
    count: 12,
})?;
```

This chooses the first DOM-bearing receipt. A real assertion should select
the exact observation from the intended step. Offline Exists and count checks
are supported. Offline Visible needs live layout and is unsupported.

## Replay and rerun mean different things

**Offline replay** inspects saved evidence and checks supported conditions.
**Live rerun** performs the actions again, producing fresh identities and effects.
Neither restores browser memory. Rerunning a purchase or submission could repeat
its effect; the spike does not promise arbitrary-site determinism.

## Decision to review

Should Archive and Views ship in 0.2.0, or remain a follow-up release? They are
implemented in the broad spike, but their release assignment was left open.

---
title: Registry
description: Share atomic state through a local JSONL file.
order: 10
---

Registry lets cooperating callers read shared state, evaluate a decision, and commit all its changes together. Every Registry uses a JSONL file. The default is `yosoi/registry.jsonl` beneath the user state directory: `XDG_STATE_HOME`, falling back to `HOME/.local/state` on Unix, or `LOCALAPPDATA` on Windows. Supply a file path to keep a workload's state separate.

## Example

### Rust

```rust
use std::error::Error;
use serde_json::json;
use yosoi::prelude as ys;
use ys::registry::{Change, Registry};

fn main() -> Result<(), Box<dyn Error>> {
    let registry = Registry::jsonl("./state/registry.jsonl")?;
    let before = registry.snapshot()?;
    let after = registry.commit(
        &before.revision,
        &[Change::Put {
            key: "example/state".to_owned(),
            value: json!({"active": 1}),
        }],
    )?;
    println!("{}", serde_json::to_string(&after)?);
    Ok(())
}
```

Use `Registry::new()?` to open the standard user file. Opening and committing can fail; an error never substitutes empty state.

### Python

```python
import yosoi as ys

registry = ys.registry.Registry("./state/registry.jsonl")
before = registry.snapshot()
after = registry.commit(
    before.revision,
    [ys.registry.Put(key="example/state", value={"active": 1})],
)
print(after.model_dump_json())
```

Use `Registry()` to open the standard user file. Handles opened independently against the same canonical file share its state. Clones also retain the original caller identity.

## Transactions and ownership

A commit locks the file's stable sidecar lock, reads and validates the journal, checks the expected revision, and appends one complete batch. It flushes that record before unlocking. A stale revision returns `Conflict`; reevaluate the decision before trying again. Clones serialize their transactions within the process. File-lock contention from independent owners returns `Busy`. Registry performs no hidden retries and holds no lock during external work. Perform the external action only after admission commits successfully.

Every line contains a version, a transaction envelope, and an event. The envelope records a transaction UUID, resulting sequence, UTC timestamp, caller instance UUID, optional PID, and application context. Use `commit_with_context` to attach an operation name, shared resource keys, and optional reservation UUID and UTC expiry. PID is diagnostic because operating systems reuse it. Consumers define their state objects and reclaim expired leases; Registry does not interpret traffic limits or execute work.

Operations are synchronous. Async callers should offload file operations to a blocking worker; the Python native binding releases the interpreter during I/O. Coordination covers cooperating local processes using the same canonical path. Hard-link aliases and network filesystems are unsupported.

A final unterminated record is treated as an interrupted write and removed before the next append. Malformed completed records and unsupported versions fail loudly. A write or flush failure can leave the outcome uncertain; inspect state before retrying.

State is bounded to 4,096 entries and 4 MiB serialized. Individual values are bounded to 64 KiB and 32 nesting levels. History is capped at 64 MiB. `compact()` replaces history with a checkpoint under the transaction lock while retaining state, identity, and revision. It discards historical transaction envelopes, so the file is a state journal rather than a permanent audit log.

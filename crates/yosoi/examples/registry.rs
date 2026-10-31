//! Offline Registry SDK example: memory by default, JSONL with an explicit path.

use std::{env, error::Error};

use serde_json::json;
use yosoi::prelude as ys;
use ys::registry::{Change, Registry};

fn main() -> Result<(), Box<dyn Error>> {
    let registry = match env::args_os().nth(1) {
        Some(path) => Registry::jsonl(path)?,
        None => Registry::default(),
    };
    let before = registry.snapshot()?;
    let after = registry.commit(
        &before.revision,
        &[Change::Put {
            key: "example/state".to_owned(),
            value: json!({"message": "shared portable DTO"}),
        }],
    )?;
    println!("{}", serde_json::to_string(&after)?);
    Ok(())
}

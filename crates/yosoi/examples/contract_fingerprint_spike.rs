//! Contract-scoped structural fingerprint experiment; see experiments/contract-fingerprints.
use std::result as std_result;
use std::{env, error::Error, io, path::Path};

#[path = "support/contract_fingerprint/mod.rs"]
mod spike;

type Result<T = ()> = std_result::Result<T, Box<dyn Error + Send + Sync>>;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.as_slice() {
        [mode, output, id] if mode == "capture" => {
            if id != "obj-001" && id != "obj-002" && !Path::new(output).join("frozen.ref.json").exists() {
                return Err(io::Error::other("freeze references before held-out capture").into());
            }
            capture(Path::new(output), id).await
        },
        [mode, output] if mode == "freeze" => spike::freeze(Path::new(output)).await,
        [mode, output, oracle] if mode == "evaluate" => spike::evaluate(Path::new(output), Path::new(oracle)).await,
        [mode, output] if mode == "sensitivity" => spike::sensitivity(Path::new(output)).await,
        [mode, output] if mode == "replay" => spike::replay(Path::new(output)).await,
        _ => Err(io::Error::other("usage: contract_fingerprint_spike capture OUTPUT ID | freeze OUTPUT | evaluate OUTPUT ORACLE | replay OUTPUT").into()),
    }
}

#[cfg(feature = "browser")]
#[path = "support/contract_fingerprint/capture.rs"]
mod capture_impl;
#[cfg(feature = "browser")]
async fn capture(output: &Path, id: &str) -> Result {
    capture_impl::capture(output, id).await
}
#[cfg(not(feature = "browser"))]
async fn capture(_output: &Path, _id: &str) -> Result {
    Err(io::Error::other("capture requires --features browser").into())
}

use std::error::Error;
use std::path::PathBuf;

use chromiumoxide_pdl::build::Generator;

fn main() -> Result<(), Box<dyn Error>> {
    let crate_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut generator = Generator::default();
    generator
        .out_dir(crate_root.join("src"))
        .allowed_deprecated_type("emulateNetworkConditions")
        .compile_pdls(&[
            crate_root.join("pdl/js_protocol.pdl"),
            crate_root.join("pdl/browser_protocol.pdl"),
        ])?;
    Ok(())
}

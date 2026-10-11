use std::error::Error;
use std::path::PathBuf;
use std::{fs, io};

use chromiumoxide_pdl::build::Generator;

fn main() -> Result<(), Box<dyn Error>> {
    let sdk_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let cdp_root = sdk_root.join("src/internal/browser/vendor/chromiumoxide_cdp");
    let mut generator = Generator::default();
    generator
        .out_dir(cdp_root.join("src"))
        .allowed_deprecated_type("emulateNetworkConditions")
        .compile_pdls(&[
            cdp_root.join("pdl/js_protocol.pdl"),
            cdp_root.join("pdl/browser_protocol.pdl"),
        ])?;
    let output = cdp_root.join("src/cdp.rs");
    let generated = fs::read_to_string(&output)?;
    let export = "    #[macro_export]\n    #[doc(hidden)]\n    macro_rules! consume_event {";
    let boundary = "    }\n}\n#[allow(clippy::wrong_self_convention)]\npub mod js_protocol {";
    if generated.matches(export).count() != 1 || generated.matches(boundary).count() != 1 {
        return Err(io::Error::other("CDP event macro generation changed").into());
    }
    let internal = generated.replace(export, "    #[doc(hidden)]\n    macro_rules! consume_event {")
        .replace(boundary, "    }\n    pub(in crate::internal::browser) use consume_event;\n}\n#[allow(clippy::wrong_self_convention)]\npub mod js_protocol {");
    fs::write(output, internal)?;
    Ok(())
}

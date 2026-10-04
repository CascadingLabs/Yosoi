#![no_main]

use libfuzzer_sys::fuzz_target;
use yosoi_web_capture::{SourceRepresentationEvidence, WebCaptureWire};

fuzz_target!(|data: &[u8]| {
    if let Ok(capture) = WebCaptureWire::from_json(data) {
        let canonical = WebCaptureWire::to_canonical_json(&capture)
            .unwrap_or_else(|error| panic!("validated capture failed serialization: {error}"));
        let reparsed = WebCaptureWire::from_json(&canonical)
            .unwrap_or_else(|error| panic!("canonical capture failed parsing: {error}"));
        assert_eq!(
            WebCaptureWire::to_canonical_json(&reparsed)
                .unwrap_or_else(|error| panic!("reparsed capture failed serialization: {error}")),
            canonical
        );
    }
    if let Ok(evidence) = SourceRepresentationEvidence::from_json(data) {
        let canonical = evidence
            .to_canonical_json()
            .unwrap_or_else(|error| panic!("validated evidence failed serialization: {error}"));
        assert_eq!(
            SourceRepresentationEvidence::from_json(&canonical)
                .unwrap_or_else(|error| panic!("canonical evidence failed parsing: {error}")),
            evidence
        );
    }
});

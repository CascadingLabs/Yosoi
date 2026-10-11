fn fixture_path(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("src/internal/web_capture/integration_tests/fixtures/web-capture")
        .join(name)
}

#[test]
fn invalid_fixture_is_reviewable_and_contains_an_unknown_root_field() {
    let path = fixture_path("invalid-v1.json");
    if env::var_os("UPDATE_CAPTURE_FIXTURES").is_some() {
        let capture = minimal_capture(fixed_capture_id(9), false);
        let bytes = WebCaptureWire::to_canonical_json(&capture).unwrap();
        let mut value: Value = serde_json::from_slice(&bytes).unwrap();
        value
            .as_object_mut()
            .unwrap()
            .insert("unknown_root_field".to_owned(), json!("must fail closed"));
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    }
    let value: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    assert_eq!(value["unknown_root_field"], json!("must fail closed"));
}

use std::{
    error::Error,
    fs::{self, File},
    path::{Path, PathBuf},
    process::Command,
};

const CORPUS_SCHEMA: &str = "yosoi.document-locator-corpus.v1";
const MATRIX_SCHEMA: &str = "yosoi.document-locator-matrix.v1";

fn repository() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

fn verifier() -> PathBuf {
    repository().join("scripts/fixtures/verify-document-locator-corpus.py")
}

fn run_verifier(root: &Path) -> Result<bool, Box<dyn Error>> {
    Ok(Command::new("python3")
        .arg(verifier())
        .arg("--root")
        .arg(root)
        .status()?
        .success())
}

fn copy_tiny_corpus(source: &Path, destination: &Path) -> Result<(), Box<dyn Error>> {
    fs::create_dir_all(destination.join("golden"))?;
    fs::create_dir_all(destination.join("advanced"))?;
    for path in ["manifest.json", "matrix.json", "advanced/manifest.json"] {
        fs::copy(source.join(path), destination.join(path))?;
    }
    let source_artifact = source.join("advanced/source.tar.gz");
    let artifact = File::create(destination.join("advanced/source.tar.gz"))?;
    artifact.set_len(fs::metadata(source_artifact)?.len())?;
    for path in [
        "accessibility-tree.json",
        "catalog.xml",
        "orders.txt",
        "product.json",
        "products.html",
        "rendered-dom.json",
    ] {
        fs::copy(
            source.join("golden").join(path),
            destination.join("golden").join(path),
        )?;
    }
    Ok(())
}

#[test]
fn document_locator_corpus_is_offline_complete_and_self_checks_rejection_paths()
-> Result<(), Box<dyn Error>> {
    let status = Command::new("python3")
        .arg(verifier())
        .arg("--self-test")
        .status()?;

    assert!(
        status.success(),
        "document-locator corpus verification failed"
    );
    Ok(())
}

#[test]
fn verifier_rejects_external_schema_and_fixture_mutations() -> Result<(), Box<dyn Error>> {
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/document-locators/v1");
    let temporary = tempfile::tempdir()?;
    copy_tiny_corpus(&source, temporary.path())?;

    let manifest_path = temporary.path().join("manifest.json");
    let original_manifest = fs::read_to_string(&manifest_path)?;
    fs::write(
        &manifest_path,
        original_manifest.replacen(CORPUS_SCHEMA, "yosoi.document-locator-corpus.v999", 1),
    )?;
    assert!(
        !run_verifier(temporary.path())?,
        "unknown corpus schema was accepted"
    );
    fs::write(&manifest_path, original_manifest)?;

    let matrix_path = temporary.path().join("matrix.json");
    let original_matrix = fs::read_to_string(&matrix_path)?;
    fs::write(
        &matrix_path,
        original_matrix.replacen(MATRIX_SCHEMA, "yosoi.document-locator-matrix.v999", 1),
    )?;
    assert!(
        !run_verifier(temporary.path())?,
        "unknown matrix schema was accepted"
    );
    fs::write(&matrix_path, original_matrix)?;

    let fixture_path = temporary.path().join("golden/products.html");
    let mut fixture = fs::read(&fixture_path)?;
    fixture.push(b'\n');
    fs::write(&fixture_path, fixture)?;
    assert!(
        !run_verifier(temporary.path())?,
        "fixture digest mutation was accepted"
    );

    Ok(())
}

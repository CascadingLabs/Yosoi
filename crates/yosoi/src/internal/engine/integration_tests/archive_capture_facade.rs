use crate::internal::engine::ArchiveError;
use crate::internal::engine::prelude as ys;

async fn capture_archive_types_remain_exact(
    archive: &ys::Archive,
    bundle: &ys::CaptureBundle,
) -> Result<(), ArchiveError> {
    let reference: ys::CaptureArchiveRef = archive.write(bundle).await?;
    let _: ys::CaptureBundle = archive.read(&reference).await?;
    Ok(())
}

#[test]
fn facade_exposes_the_typed_capture_archive_pair() {
    let _ = capture_archive_types_remain_exact;
}

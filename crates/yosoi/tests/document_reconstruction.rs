use std::error::Error;

use yosoi::prelude as ys;

#[test]
fn facade_reconstructs_from_typed_identity_profile_and_bytes() -> Result<(), Box<dyn Error>> {
    let epoch = ys::DocumentEpoch::try_from(11_u64)?;
    let profile = ys::DocumentProfile::rendered_dom(epoch);
    let id = ys::DocumentId::try_new("archived-rendered-dom")?;
    let bytes = br#"{"nodes":[]}"#.to_vec();

    let document = ys::Document::from_profile(id.clone(), profile, bytes.clone())?;
    if document.id() != &id || document.profile() != profile || document.bytes() != bytes.as_slice()
    {
        return Err("facade reconstruction changed a durable Document input".into());
    }
    if document.profile().epoch() != Some(epoch) {
        return Err("facade reconstruction lost the rendered document epoch".into());
    }
    Ok(())
}

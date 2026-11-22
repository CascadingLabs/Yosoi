use crate::surface::SurfaceError;

use super::model::{PixelArtifact, PixelEdgeTransform, PixelOperation, PixelTransform};

/// Constructs an explicit resize transform using exact dimension ratios.
pub fn resize_transform(
    parent: &PixelArtifact,
    operation: PixelOperation,
    width: u32,
    height: u32,
) -> Result<PixelTransform, SurfaceError> {
    let parent_space = parent.info.coordinate_space;
    if width == 0 || height == 0 || parent_space.width == 0 || parent_space.height == 0 {
        return Err(SurfaceError::Invalid(
            "resize transform requires positive dimensions".into(),
        ));
    }
    match &operation {
        PixelOperation::Overview { .. } | PixelOperation::Resize { .. } => {}
        _ => {
            return Err(SurfaceError::Invalid(
                "resize transform requires overview or resize operation".into(),
            ));
        }
    }
    Ok(PixelTransform {
        version: 1,
        operation,
        parent_identity: Some(parent.info.identity.clone()),
        parent_sha256: Some(parent.info.sha256.clone()),
        parent_media_type: Some(parent.info.media_type.clone()),
        parent_space: Some(parent_space),
        output_to_parent: Some(PixelEdgeTransform {
            scale_x_numerator: parent_space.width,
            scale_x_denominator: width,
            scale_y_numerator: parent_space.height,
            scale_y_denominator: height,
            translate_x: 0,
            translate_y: 0,
        }),
    })
}

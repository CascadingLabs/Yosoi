use std::mem;

use crate::internal::documents::region_membership::tree_coordinate_bytes;
use crate::internal::documents::{
    DocumentId, NativeCoordinate, OutputId, ProjectedValue, RegionLineage, TreeCoordinate,
};

pub(super) fn finding_output_bytes(
    document_id: &DocumentId,
    output_id: &OutputId,
    coordinate: &TreeCoordinate,
    value: &ProjectedValue,
    parent_region: Option<&RegionLineage>,
) -> Option<u64> {
    let mut size = u64::try_from(document_id.as_str().len()).ok()?;
    size = size.checked_add(u64::try_from(output_id.as_str().len()).ok()?)?;
    size = size.checked_add(tree_coordinate_bytes(coordinate)?)?;
    let value_size = match value {
        ProjectedValue::Text(text) => u64::try_from(text.len()).ok()?,
        ProjectedValue::TextWithCaptures { text, captures } => {
            let mut bytes = u64::try_from(text.len()).ok()?;
            for (name, value) in captures {
                bytes = bytes.checked_add(u64::try_from(name.len()).ok()?)?;
                bytes = bytes.checked_add(u64::try_from(value.len()).ok()?)?;
            }
            bytes
        }
        ProjectedValue::Attribute { name, value } => u64::try_from(name.len())
            .ok()?
            .checked_add(u64::try_from(value.len()).ok()?)?,
        ProjectedValue::Node(_) => u64::try_from(document_id.as_str().len())
            .ok()?
            .checked_add(tree_coordinate_bytes(coordinate)?)?,
        ProjectedValue::Json(_) => 0,
    };
    size = size.checked_add(value_size)?;
    if let Some(lineage) = parent_region {
        size = size.checked_add(u64::try_from(lineage.region_id().as_str().len()).ok()?)?;
        size = size.checked_add(u64::try_from(mem::size_of::<u64>()).ok()?)?;
        let NativeCoordinate::SourceTree(region_coordinate) = lineage.coordinate() else {
            return None;
        };
        size = size.checked_add(tree_coordinate_bytes(region_coordinate)?)?;
    }
    Some(size)
}

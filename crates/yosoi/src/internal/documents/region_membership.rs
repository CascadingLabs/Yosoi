use std::mem;

use thiserror::Error;

use crate::internal::documents::{
    DomCoordinate, LocateFailure, NativeCoordinate, RegionLineage, ResourceLimit, TreeCoordinate,
};

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum RegionByteError {
    #[error("region coordinate is unsupported for retained membership")]
    UnsupportedCoordinate,
    #[error("retained region byte count overflowed")]
    Overflow,
    #[error("retained region bytes exceed the output limit")]
    LimitExceeded { observed: u64 },
}

pub fn reserve_region_bytes(
    current: &mut u64,
    maximum: u64,
    region: &RegionLineage,
) -> Result<(), RegionByteError> {
    let added = region_bytes(region)?;
    let observed = current
        .checked_add(added)
        .ok_or(RegionByteError::Overflow)?;
    if observed > maximum {
        Err(RegionByteError::LimitExceeded { observed })
    } else {
        *current = observed;
        Ok(())
    }
}

pub fn region_output_failure(
    error: RegionByteError,
    maximum: u64,
    invalid_code: &'static str,
) -> LocateFailure {
    match error {
        RegionByteError::UnsupportedCoordinate => LocateFailure::InvalidPlan {
            code: invalid_code.to_owned(),
        },
        RegionByteError::Overflow => LocateFailure::LimitExhausted {
            limit: ResourceLimit::OutputBytes,
            maximum,
            observed: u64::MAX,
        },
        RegionByteError::LimitExceeded { observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::OutputBytes,
            maximum,
            observed,
        },
    }
}

fn region_bytes(region: &RegionLineage) -> Result<u64, RegionByteError> {
    let mut size =
        u64::try_from(region.region_id().as_str().len()).map_err(|_| RegionByteError::Overflow)?;
    size = size
        .checked_add(u64::try_from(mem::size_of::<u64>()).map_err(|_| RegionByteError::Overflow)?)
        .ok_or(RegionByteError::Overflow)?;
    let coordinate_bytes = match region.coordinate() {
        NativeCoordinate::SourceTree(coordinate) => {
            tree_coordinate_bytes(coordinate).ok_or(RegionByteError::Overflow)?
        }
        NativeCoordinate::RenderedDom(coordinate) => {
            dom_coordinate_bytes(coordinate).ok_or(RegionByteError::Overflow)?
        }
        _ => return Err(RegionByteError::UnsupportedCoordinate),
    };
    size.checked_add(coordinate_bytes)
        .ok_or(RegionByteError::Overflow)
}

pub fn tree_coordinate_bytes(coordinate: &TreeCoordinate) -> Option<u64> {
    let entries = u64::try_from(coordinate.child_path().len()).ok()?;
    entries.checked_mul(u64::try_from(mem::size_of::<u32>()).ok()?)
}

pub fn dom_coordinate_bytes(coordinate: &DomCoordinate) -> Option<u64> {
    if coordinate.document_epoch().get() == 0 || coordinate.node_id().get() == 0 {
        return None;
    }
    u64::try_from(mem::size_of::<u64>()).ok()?.checked_mul(2)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::internal::documents::{RegionId, TreeCoordinate};
    use std::{error::Error, io};

    fn region() -> Result<RegionLineage, Box<dyn Error>> {
        Ok(RegionLineage::new(
            RegionId::try_new("product")?,
            0,
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1], None)?),
        ))
    }

    #[test]
    fn reservation_is_atomic_at_the_exact_boundary() -> Result<(), Box<dyn Error>> {
        let region = region()?;
        let exact = region_bytes(&region)?;
        let mut retained = 0;
        reserve_region_bytes(&mut retained, exact, &region)?;
        if retained != exact {
            return Err(
                io::Error::other("successful reservation used the wrong byte count").into(),
            );
        }

        let before = retained;
        if !matches!(
            reserve_region_bytes(&mut retained, exact, &region),
            Err(RegionByteError::LimitExceeded { .. })
        ) {
            return Err(io::Error::other("over-limit reservation was not rejected").into());
        }
        if retained != before {
            return Err(io::Error::other("failed reservation changed the byte count").into());
        }
        Ok(())
    }
}

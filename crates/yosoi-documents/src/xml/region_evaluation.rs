use roxmltree::Node;

use crate::region_membership::{RegionByteError, reserve_region_bytes};
use crate::{NativeCoordinate, Plan, RegionId, RegionLineage, ResourceBudget};

use super::query::CompiledXmlPlan;
use super::{QueryWorkBudget, XmlDocument, XmlError};

pub(super) type RegionResults<'tree, 'input> =
    Vec<(RegionId, Vec<(Node<'tree, 'input>, RegionLineage)>)>;

pub(super) fn collect_region_memberships<'tree, 'input>(
    document: &'tree XmlDocument<'input>,
    plan: &Plan,
    compiled_plan: &CompiledXmlPlan,
    budget: ResourceBudget,
    work_budget: &mut QueryWorkBudget,
    total_output_bytes: &mut u64,
) -> Result<(RegionResults<'tree, 'input>, Vec<RegionLineage>), XmlError> {
    let mut region_results = RegionResults::new();
    let mut matched_regions = Vec::new();
    for (region_index, region) in plan.regions().iter().enumerate() {
        let nodes = document.select(
            compiled_plan.region_query(region_index)?,
            document.tree.root(),
            budget,
            work_budget,
        )?;
        let mut memberships = Vec::with_capacity(nodes.len());
        for (ordinal, node) in nodes.into_iter().enumerate() {
            let region_ordinal = u64::try_from(ordinal).map_err(|_| XmlError::InvalidResult)?;
            let coordinate = document.coordinate(node, work_budget)?;
            let lineage = RegionLineage::new(
                region.id().clone(),
                region_ordinal,
                NativeCoordinate::SourceTree(coordinate),
            );
            reserve_bytes(total_output_bytes, budget.max_output_bytes(), &lineage)?;
            matched_regions.push(lineage.clone());
            memberships.push((node, lineage));
        }
        region_results.push((region.id().clone(), memberships));
    }
    Ok((region_results, matched_regions))
}

fn reserve_bytes(
    total_output_bytes: &mut u64,
    maximum: u64,
    lineage: &RegionLineage,
) -> Result<(), XmlError> {
    reserve_region_bytes(total_output_bytes, maximum, lineage).map_err(|error| match error {
        RegionByteError::UnsupportedCoordinate => XmlError::InvalidResult,
        RegionByteError::Overflow => XmlError::OutputLimitExceeded {
            maximum,
            observed: u64::MAX,
        },
        RegionByteError::LimitExceeded { observed } => {
            XmlError::OutputLimitExceeded { maximum, observed }
        }
    })
}

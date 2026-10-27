//! Frozen manual discovery from obj-001 and obj-002; no fixture values used here.
use super::{Result as SpikeResult, fail, structure::Dom};
use serde::{Deserialize, Serialize};
use yosoi::{
    documents::Document,
    locators::{self, Finding, LocateOutcome, LocateResult, NativeCoordinate},
    prelude as ys,
};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize, ys::Contract)]
#[ys(id="qscrape_product", description="One eShop product", root=ys::locator::css("[data-shop-part='product-detail']"))]
pub(super) struct Product {
    #[ys(description = "Product identity attached to the selected root")]
    pub id: String,
    #[ys(description = "Product name")]
    pub name: String,
    #[ys(description = "Displayed USD purchase price")]
    pub price: String,
    #[ys(description = "Color identified by its fact label")]
    pub color: String,
    #[ys(description = "Material identified by its fact label")]
    pub material: String,
    #[ys(description = "Stock availability text, including explicit unavailability")]
    pub stock: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct Recipe {
    pub root: String,
    pub name: String,
    pub price: String,
    pub stock: String,
    pub fact_value: String,
    pub material_label: String,
    pub color_label: String,
}

impl Default for Recipe {
    fn default() -> Self {
        Self {
            root: "[data-shop-part='product-detail']".into(),
            name: "h1".into(),
            price: ".shop-detail-price".into(),
            stock: ".shop-availability".into(),
            fact_value: ".shop-product-facts > div > .shop-fact-value".into(),
            material_label: "Material".into(),
            color_label: "Color".into(),
        }
    }
}

impl Recipe {
    pub fn plan(&self) -> SpikeResult<ys::Plan> {
        let root = locators::css(&self.root)?.each_as_region("qscrape_product")?;
        Ok(ys::Plan::new([
            locators::output(
                "id",
                locators::css(&self.root)?.attribute("data-product-id")?,
            )?,
            locators::output("name", root.find(locators::css(&self.name)?).text())?,
            locators::output("price", root.find(locators::css(&self.price)?).text())?,
            locators::output("stock", root.find(locators::css(&self.stock)?).text())?,
            locators::output(
                "material",
                root.find(locators::css(&self.fact_value)?).text(),
            )?,
            locators::output("color", root.find(locators::css(&self.fact_value)?).text())?,
        ])?)
    }

    pub fn locate(&self, document: &Document, plan: &ys::Plan) -> SpikeResult<LocateOutcome> {
        let raw = document.parse()?.locate(plan);
        let LocateOutcome::Matched { result } = raw else {
            return Ok(raw);
        };
        let [root] = result.regions() else {
            return fail("expected exactly one product root");
        };
        let dom = Dom::read(document)?;
        let mut findings = Vec::new();
        for finding in result.findings() {
            let label = match finding.output_id().as_str() {
                "material" => Some(&self.material_label),
                "color" => Some(&self.color_label),
                _ => None,
            };
            if let Some(label) = label {
                let NativeCoordinate::RenderedDom(coordinate) = finding.coordinate() else {
                    return fail("expected DOM fact evidence");
                };
                let parent = dom
                    .node(coordinate.node_id().get())?
                    .parent
                    .ok_or_else(|| super::error("fact has no parent"))?;
                let labels = dom
                    .node(parent)?
                    .children
                    .iter()
                    .filter_map(|id| dom.node(*id).ok())
                    .filter(|node| {
                        node.attributes.iter().flatten().any(|attribute| {
                            attribute.name == "class"
                                && attribute
                                    .value
                                    .split_whitespace()
                                    .any(|value| value == "shop-fact-label")
                        })
                    })
                    .map(|node| dom.text(node.id))
                    .collect::<SpikeResult<Vec<_>>>()?;
                if labels.len() != 1 || labels.first() != Some(label) {
                    continue;
                }
            }
            if finding.output_id().as_str() == "id" && finding.coordinate() != root.coordinate() {
                return fail("product ID evidence does not identify the selected root");
            }
            findings.push(Finding::try_new(
                document.id().clone(),
                finding.output_id().clone(),
                u64::try_from(findings.len())?,
                finding.coordinate().clone(),
                finding.value().clone(),
                finding.completeness().clone(),
                Some(root.clone()),
            )?);
        }
        Ok(LocateOutcome::Matched {
            result: LocateResult::try_new_with_regions(
                document.id().clone(),
                result.regions().to_vec(),
                findings,
            )?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) enum Stock {
    Available(u32),
    Unavailable,
}

pub(super) fn runtime_validate(product: &Product, requested_id: &str) -> SpikeResult<Stock> {
    if product.id != requested_id
        || [&product.name, &product.color, &product.material]
            .iter()
            .any(|v| v.trim().is_empty())
    {
        return fail("product identity mismatch or blank required text");
    }
    price_cents(&product.price)?;
    if product.stock.trim_end_matches('.') == "Currently unavailable" {
        return Ok(Stock::Unavailable);
    }
    let quantity = product
        .stock
        .strip_suffix(" in stock and ready to find a home.")
        .ok_or_else(|| super::error("unknown stock format"))?
        .parse::<u32>()?;
    if quantity == 0 {
        return fail("available stock must be positive");
    }
    Ok(Stock::Available(quantity))
}

pub(super) fn price_cents(price: &str) -> SpikeResult<u64> {
    let (whole, fraction) = price
        .strip_prefix('$')
        .and_then(|v| v.split_once('.'))
        .ok_or_else(|| super::error("expected USD price"))?;
    if whole.is_empty()
        || fraction.len() != 2
        || !whole
            .bytes()
            .chain(fraction.bytes())
            .all(|b| b.is_ascii_digit())
    {
        return fail("invalid USD decimal price");
    }
    whole
        .parse::<u64>()?
        .checked_mul(100)
        .and_then(|v| v.checked_add(fraction.parse::<u64>().ok()?))
        .ok_or_else(|| super::error("price overflow"))
}

pub(super) fn extract(located: &LocateOutcome) -> SpikeResult<Product> {
    let mut records = Product::extract(located).validate().require_all()?;
    if records.len() != 1 {
        return fail("exactly one validated Product required");
    }
    records
        .pop()
        .ok_or_else(|| super::error("validated product missing"))
}

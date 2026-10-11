use crate::internal::contract_validation::ValidationCode;
use crate::internal::contracts::ContractValue;
use crate::internal::documents::ProjectedValue;
use serde::{Deserialize, Serialize, de::Error as _};
use std::fmt::{self, Formatter};

mod sealed {
    pub trait RuntimeContractValue {}
    impl RuntimeContractValue for String {}
    impl RuntimeContractValue for super::Money {}
}

#[doc(hidden)]
pub trait RuntimeContractValue: ContractValue + sealed::RuntimeContractValue + Sized {
    fn from_projected(value: &ProjectedValue) -> Result<Self, RuntimeValueIssue>;
}

impl RuntimeContractValue for String {
    fn from_projected(value: &ProjectedValue) -> Result<Self, RuntimeValueIssue> {
        match value {
            ProjectedValue::Text(text) | ProjectedValue::TextWithCaptures { text, .. } => {
                Ok(text.clone())
            }
            ProjectedValue::Attribute { value, .. } => Ok(value.clone()),
            _ => Err(RuntimeValueIssue::UnsupportedProjectedValue),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Currency {
    Usd,
}

/// A validated USD amount.
///
/// Runtime text conversion accepts only `$`, an optional `-`, one or more
/// ASCII whole digits, `.`, and exactly two ASCII fractional digits. Negative
/// amounts parse but fail the first-slice semantic validation rule.
#[derive(Clone, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Money {
    minor_units: i64,
    currency: Currency,
}

impl fmt::Debug for Money {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Money")
            .field("currency", &self.currency)
            .finish_non_exhaustive()
    }
}

impl<'de> Deserialize<'de> for Money {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireMoney {
            minor_units: i64,
            currency: Currency,
        }
        let wire = WireMoney::deserialize(deserializer)?;
        if wire.minor_units.is_negative() {
            return Err(D::Error::custom("money cannot be negative"));
        }
        Ok(Self {
            minor_units: wire.minor_units,
            currency: wire.currency,
        })
    }
}

impl Money {
    #[doc(hidden)]
    pub const fn from_archived_usd_minor_units(minor_units: i64) -> Option<Self> {
        if minor_units.is_negative() {
            None
        } else {
            Some(Self {
                minor_units,
                currency: Currency::Usd,
            })
        }
    }

    pub const fn minor_units(&self) -> i64 {
        self.minor_units
    }
    pub const fn currency(&self) -> Currency {
        self.currency
    }
}

impl fmt::Display for Money {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        let magnitude = self.minor_units.unsigned_abs();
        let whole = magnitude.div_euclid(100);
        let fraction = magnitude.rem_euclid(100);
        write!(formatter, "${whole}.{fraction:02}")
    }
}

impl ContractValue for Money {
    const TYPE_ID: &'static str = "money.usd";
}

impl RuntimeContractValue for Money {
    fn from_projected(value: &ProjectedValue) -> Result<Self, RuntimeValueIssue> {
        let (ProjectedValue::Text(text) | ProjectedValue::TextWithCaptures { text, .. }) = value
        else {
            return Err(RuntimeValueIssue::UnsupportedProjectedValue);
        };
        let (money, negative) = parse_usd(text).ok_or(RuntimeValueIssue::ConversionFailed)?;
        if negative {
            Err(RuntimeValueIssue::SemanticValidationFailed {
                code: ValidationCode::NegativeMoney,
            })
        } else {
            Ok(money)
        }
    }
}

fn parse_usd(value: &str) -> Option<(Money, bool)> {
    let value = value.strip_prefix('$')?;
    let (negative, unsigned) = value
        .strip_prefix('-')
        .map_or((false, value), |unsigned| (true, unsigned));
    let (whole, fraction) = unsigned.split_once('.')?;
    if whole.is_empty()
        || fraction.len() != 2
        || !whole.chars().all(|character| character.is_ascii_digit())
        || !fraction.chars().all(|character| character.is_ascii_digit())
    {
        return None;
    }
    let whole = whole.parse::<i64>().ok()?;
    let fraction = fraction.parse::<i64>().ok()?;
    let magnitude = whole.checked_mul(100)?.checked_add(fraction)?;
    let minor_units = if negative {
        magnitude.checked_neg()?
    } else {
        magnitude
    };
    Some((
        Money {
            minor_units,
            currency: Currency::Usd,
        },
        negative,
    ))
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RuntimeValueIssue {
    UnsupportedProjectedValue,
    ConversionFailed,
    SemanticValidationFailed { code: ValidationCode },
}

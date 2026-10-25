use crate::internal::contracts::ContractValue;
use crate::internal::documents::ProjectedValue;
use serde::{Deserialize, Serialize};

mod sealed {
    pub trait RuntimeContractValue {}
    impl RuntimeContractValue for String {}
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
/// Projection conversion rejection for one Contract field.
pub enum RuntimeValueIssue {
    /// The projection variant cannot be converted into the requested scalar vocabulary.
    UnsupportedProjectedValue,
    /// Supported projection text could not be parsed into the requested scalar representation.
    ConversionFailed,
}

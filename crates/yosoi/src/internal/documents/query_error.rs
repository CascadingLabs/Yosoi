use thiserror::Error;

use crate::internal::documents::JsonQuerySyntaxError;

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum QueryError {
    #[error("query expression cannot be empty")]
    EmptyExpression,
    #[error("regular expression syntax is invalid or unsupported")]
    InvalidRegexSyntax,
    #[error("attribute name cannot be empty")]
    EmptyAttributeName,
    #[error("region identity cannot be empty")]
    EmptyRegionId,
    #[error("capture projection must request at least one named capture")]
    EmptyCaptureList,
    #[error("capture name cannot be empty")]
    EmptyCaptureName,
    #[error("capture name {name} is requested more than once")]
    DuplicateCaptureName { name: String },
    #[error("capture name {name} does not exist in the regular expression")]
    UnknownCaptureName { name: String },
    #[error("query length cannot be represented as u64")]
    LengthOverflow,
    #[error("namespace prefix is invalid")]
    InvalidNamespacePrefix,
    #[error("namespace URI cannot be empty")]
    EmptyNamespaceUri,
    #[error("namespace prefix is already bound")]
    DuplicateNamespacePrefix,
    #[error("namespace prefix is reserved")]
    ReservedNamespacePrefix,
    #[error("namespace prefix has no query binding")]
    UnboundNamespacePrefix,
    #[error("namespace bindings are supported only for XML CSS and XPath queries")]
    NamespacesRequireXmlLocator,
    #[error("serialized namespace bindings must be ordered by prefix")]
    NonCanonicalNamespaceBindingOrder,
    #[error("the default namespace applies only to XML CSS queries")]
    DefaultNamespaceOnlyForCss,
    #[error("XML attribute projection name is not a supported QName")]
    InvalidAttributeNamespaceName,
    #[error(transparent)]
    InvalidJsonQuery(#[from] JsonQuerySyntaxError),
}

use thiserror::Error;

use crate::internal::documents::JsonQuerySyntaxError;

/// Authored query, projection, namespace, or portable accounting rejected before usable execution.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum QueryError {
    /// The selected query vocabulary requires nonempty expression text.
    #[error("query expression cannot be empty")]
    EmptyExpression,
    /// The supported regular-expression compiler rejects the authored pattern.
    #[error("regular expression syntax is invalid or unsupported")]
    InvalidRegexSyntax,
    /// Attribute projection has no nonblank name to select.
    #[error("attribute name cannot be empty")]
    EmptyAttributeName,
    /// Repeated-region declaration has no nonblank lineage identity.
    #[error("region identity cannot be empty")]
    EmptyRegionId,
    /// Named-capture projection requests no capture names.
    #[error("capture projection must request at least one named capture")]
    EmptyCaptureList,
    /// A requested capture name is blank.
    #[error("capture name cannot be empty")]
    EmptyCaptureName,
    /// The capture selection repeats a named capture.
    #[error("capture name {name} is requested more than once")]
    DuplicateCaptureName {
        /// Repeated authored capture name.
        name: String,
    },
    /// A requested capture name is absent from the compiled regular expression.
    #[error("capture name {name} does not exist in the regular expression")]
    UnknownCaptureName {
        /// Authored capture name without a matching pattern definition.
        name: String,
    },
    /// Query text or namespace byte accounting cannot fit its portable u64 representation.
    #[error("query length cannot be represented as u64")]
    LengthOverflow,
    /// A query-local namespace prefix fails the supported XML name syntax.
    #[error("namespace prefix is invalid")]
    InvalidNamespacePrefix,
    /// An explicit namespace binding has no nonblank URI.
    #[error("namespace URI cannot be empty")]
    EmptyNamespaceUri,
    /// More than one binding uses the same query prefix, including a repeated default binding.
    #[error("namespace prefix is already bound")]
    DuplicateNamespacePrefix,
    /// An authored binding tries to override reserved XML namespace prefixes.
    #[error("namespace prefix is reserved")]
    ReservedNamespacePrefix,
    /// Query syntax refers to a prefix absent from its explicit bindings.
    #[error("namespace prefix has no query binding")]
    UnboundNamespacePrefix,
    /// Namespace metadata was attached to a query outside XML CSS/XPath vocabulary.
    #[error("namespace bindings are supported only for XML CSS and XPath queries")]
    NamespacesRequireXmlLocator,
    /// Imported namespace bindings are not in the required canonical prefix order.
    #[error("serialized namespace bindings must be ordered by prefix")]
    NonCanonicalNamespaceBindingOrder,
    /// Default namespace semantics were requested outside the supported CSS path.
    #[error("the default namespace applies only to XML CSS queries")]
    DefaultNamespaceOnlyForCss,
    /// XML attribute projection names an unsupported or invalid qualified name.
    #[error("XML attribute projection name is not a supported QName")]
    InvalidAttributeNamespaceName,
    /// JSON Pointer or supported JSONPath syntax validation rejected the expression.
    #[error(transparent)]
    InvalidJsonQuery(#[from] JsonQuerySyntaxError),
}

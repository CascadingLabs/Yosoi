#[derive(Clone, Debug)]
pub(in crate::internal::documents::xml) struct SelectorList {
    pub(in crate::internal::documents::xml) selectors: Vec<Selector>,
    pub(in crate::internal::documents::xml) steps: usize,
}

impl SelectorList {
    pub(in crate::internal::documents::xml) const fn step_count(&self) -> usize {
        self.steps
    }
}

#[derive(Clone, Debug)]
pub(in crate::internal::documents::xml) struct Selector {
    pub(in crate::internal::documents::xml) compounds: Vec<CompoundSelector>,
    pub(in crate::internal::documents::xml) combinators: Vec<Combinator>,
}

#[derive(Clone, Copy, Debug)]
pub(in crate::internal::documents::xml) enum Combinator {
    Child,
    Descendant,
}

#[derive(Clone, Debug)]
pub(in crate::internal::documents::xml) struct CompoundSelector {
    pub(in crate::internal::documents::xml) name: Option<NameTest>,
    pub(in crate::internal::documents::xml) conditions: Vec<SimpleCondition>,
}

#[derive(Clone, Debug)]
pub(in crate::internal::documents::xml) enum SimpleCondition {
    Id(String),
    Class(String),
    Attribute(AttributeTest),
    FirstChild,
}

#[derive(Clone, Debug)]
pub(in crate::internal::documents::xml) struct AttributeTest {
    pub(in crate::internal::documents::xml) name: NameTest,
    pub(in crate::internal::documents::xml) value: Option<String>,
}

#[derive(Clone, Debug)]
pub(in crate::internal::documents::xml) struct NameTest {
    pub(in crate::internal::documents::xml) namespace: NamespaceTest,
    pub(in crate::internal::documents::xml) local_name: Option<String>,
}

#[derive(Clone, Debug)]
pub(in crate::internal::documents::xml) enum NamespaceTest {
    Any,
    None,
    Uri(String),
}

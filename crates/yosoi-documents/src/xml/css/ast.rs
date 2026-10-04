#[derive(Clone, Debug)]
pub(in crate::xml) struct SelectorList {
    pub(in crate::xml) selectors: Vec<Selector>,
    pub(in crate::xml) steps: usize,
}

impl SelectorList {
    pub(in crate::xml) const fn step_count(&self) -> usize {
        self.steps
    }
}

#[derive(Clone, Debug)]
pub(in crate::xml) struct Selector {
    pub(in crate::xml) compounds: Vec<CompoundSelector>,
    pub(in crate::xml) combinators: Vec<Combinator>,
}

#[derive(Clone, Copy, Debug)]
pub(in crate::xml) enum Combinator {
    Child,
    Descendant,
}

#[derive(Clone, Debug)]
pub(in crate::xml) struct CompoundSelector {
    pub(in crate::xml) name: Option<NameTest>,
    pub(in crate::xml) conditions: Vec<SimpleCondition>,
}

#[derive(Clone, Debug)]
pub(in crate::xml) enum SimpleCondition {
    Id(String),
    Class(String),
    Attribute(AttributeTest),
    FirstChild,
}

#[derive(Clone, Debug)]
pub(in crate::xml) struct AttributeTest {
    pub(in crate::xml) name: NameTest,
    pub(in crate::xml) value: Option<String>,
}

#[derive(Clone, Debug)]
pub(in crate::xml) struct NameTest {
    pub(in crate::xml) namespace: NamespaceTest,
    pub(in crate::xml) local_name: Option<String>,
}

#[derive(Clone, Debug)]
pub(in crate::xml) enum NamespaceTest {
    Any,
    None,
    Uri(String),
}

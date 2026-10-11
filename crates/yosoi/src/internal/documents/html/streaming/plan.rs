use super::config::MAX_STREAMING_ATTRIBUTES;
use super::names::{BODY, CLASS, COLGROUP, HEAD, HTML, ID, NameKey, TBODY};
use super::support::{
    Combinator, CssCompoundSelector, CssSimpleSelector, Projection, TreeQuery, XPathAxis,
    XPathNameTest, XPathStep, memmem,
};

#[derive(Clone)]
pub(super) enum CompiledTest {
    Id(String),
    Class(String),
    AttributePresent(NameKey),
    AttributeEquals(NameKey, String),
}

#[derive(Clone)]
pub(super) struct CompiledCompound {
    pub(super) tag: NameKey,
    pub(super) tests: Vec<CompiledTest>,
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum StreamingShape {
    Root,
    Descendant,
    Child,
}

#[derive(Clone)]
pub(super) enum StreamingProjection {
    Text,
    Attribute { key: NameKey, name: String },
    Node,
}

#[derive(Clone)]
pub(in crate::internal::documents::html) enum CompiledStreamingPlan {
    Selector(Box<CompiledSelectorPlan>),
    TreeText(Box<CompiledTreeTextPlan>),
}

#[derive(Clone)]
pub(in crate::internal::documents::html) struct CompiledTreeTextPlan {
    pub(super) needle: Box<str>,
    pub(super) finder: memmem::Finder<'static>,
    pub(super) minimum_match_shift: usize,
    pub(super) node_projection: bool,
}

#[derive(Clone)]
pub(in crate::internal::documents::html) struct CompiledSelectorPlan {
    pub(super) leftmost: CompiledCompound,
    pub(super) rightmost: CompiledCompound,
    pub(super) leftmost_close: memmem::Finder<'static>,
    pub(super) leftmost_close_len: usize,
    pub(super) attribute_names: [Option<NameKey>; MAX_STREAMING_ATTRIBUTES],
    pub(super) attribute_name_count: usize,
    pub(super) leftmost_test_count: u64,
    pub(super) rightmost_test_count: u64,
    pub(super) shape: StreamingShape,
    pub(super) projection: StreamingProjection,
}

pub(in crate::internal::documents::html) fn compile_plan(
    plan: &super::super::CompiledTreePlan,
) -> Option<CompiledStreamingPlan> {
    if !plan.regions.is_empty() || plan.outputs.len() != 1 {
        return None;
    }
    let output = plan.outputs.first()?;
    if output.parent_region.is_some() {
        return None;
    }
    if let TreeQuery::TreeTextContains(needle) = &output.query {
        return match &output.projection {
            Projection::DescendantText => Some(CompiledStreamingPlan::TreeText(Box::new(
                CompiledTreeTextPlan {
                    needle: needle.clone().into_boxed_str(),
                    finder: memmem::Finder::new(needle.as_bytes()).into_owned(),
                    minimum_match_shift: minimum_match_shift(needle.as_bytes())?,
                    node_projection: false,
                },
            ))),
            Projection::NodeReference => Some(CompiledStreamingPlan::TreeText(Box::new(
                CompiledTreeTextPlan {
                    needle: needle.clone().into_boxed_str(),
                    finder: memmem::Finder::new(needle.as_bytes()).into_owned(),
                    minimum_match_shift: minimum_match_shift(needle.as_bytes())?,
                    node_projection: true,
                },
            ))),
            _ => None,
        };
    }
    let projection = match &output.projection {
        Projection::DescendantText => StreamingProjection::Text,
        Projection::Attribute(name) => StreamingProjection::Attribute {
            key: NameKey::from_ascii_casefold(name.as_bytes())?,
            name: name.to_ascii_lowercase(),
        },
        Projection::NodeReference => StreamingProjection::Node,
        _ => return None,
    };
    let (leftmost, rightmost, shape, leftmost_name) = match &output.query {
        TreeQuery::Css(selectors) => {
            let selector = one_element(&selectors.groups)?;
            match selector.steps.as_slice() {
                [root] if !matches!(projection, StreamingProjection::Text) => {
                    let compiled = compile_compound(&root.compound)?;
                    let name = root.compound.tag_name.as_ref()?.to_ascii_lowercase();
                    (compiled.clone(), compiled, StreamingShape::Root, name)
                }
                [left, right] => {
                    let shape = match right.relation? {
                        Combinator::Descendant => StreamingShape::Descendant,
                        Combinator::Child => StreamingShape::Child,
                    };
                    (
                        compile_compound(&left.compound)?,
                        compile_compound(&right.compound)?,
                        shape,
                        left.compound.tag_name.as_ref()?.to_ascii_lowercase(),
                    )
                }
                _ => return None,
            }
        }
        TreeQuery::XPath(path) => compile_xpath(path, &projection)?,
        TreeQuery::TreeTextContains(_) => return None,
    };
    if leftmost.tests.len().checked_add(rightmost.tests.len())? > MAX_STREAMING_ATTRIBUTES {
        return None;
    }
    let (mut attribute_names, mut attribute_name_count) =
        compile_attribute_names(&leftmost, &rightmost)?;
    if let StreamingProjection::Attribute { key, .. } = &projection
        && !attribute_names
            .get(..attribute_name_count)?
            .contains(&Some(*key))
    {
        *attribute_names.get_mut(attribute_name_count)? = Some(*key);
        attribute_name_count = attribute_name_count.checked_add(1)?;
    }
    let leftmost_close = format!("</{leftmost_name}>").into_bytes();
    Some(CompiledStreamingPlan::Selector(Box::new(
        CompiledSelectorPlan {
            leftmost_test_count: u64::try_from(leftmost.tests.len()).ok()?,
            rightmost_test_count: u64::try_from(rightmost.tests.len()).ok()?,
            leftmost_close: memmem::Finder::new(&leftmost_close).into_owned(),
            leftmost_close_len: leftmost_close.len(),
            attribute_names,
            attribute_name_count,
            leftmost,
            rightmost,
            shape,
            projection,
        },
    )))
}

fn minimum_match_shift(pattern: &[u8]) -> Option<usize> {
    if pattern.is_empty() {
        return None;
    }
    let mut prefix = vec![0_usize; pattern.len()];
    let mut matched = 0_usize;
    for position in 1..pattern.len() {
        let byte = *pattern.get(position)?;
        while matched > 0 && pattern.get(matched).copied() != Some(byte) {
            matched = *prefix.get(matched.checked_sub(1)?)?;
        }
        if pattern.get(matched).copied() == Some(byte) {
            matched = matched.checked_add(1)?;
        }
        *prefix.get_mut(position)? = matched;
    }
    pattern.len().checked_sub(prefix.last().copied()?)
}

fn compile_attribute_names(
    leftmost: &CompiledCompound,
    rightmost: &CompiledCompound,
) -> Option<([Option<NameKey>; MAX_STREAMING_ATTRIBUTES], usize)> {
    let mut names = [None; MAX_STREAMING_ATTRIBUTES];
    let mut len = 0_usize;
    for test in leftmost.tests.iter().chain(&rightmost.tests) {
        let name = match test {
            CompiledTest::Id(_) => ID,
            CompiledTest::Class(_) => CLASS,
            CompiledTest::AttributePresent(name) | CompiledTest::AttributeEquals(name, _) => *name,
        };
        if names
            .get(..len)?
            .iter()
            .flatten()
            .any(|candidate| *candidate == name)
        {
            continue;
        }
        *names.get_mut(len)? = Some(name);
        len = len.checked_add(1)?;
    }
    Some((names, len))
}

fn compile_compound(selector: &CssCompoundSelector) -> Option<CompiledCompound> {
    let tag = NameKey::from_ascii_casefold(selector.tag_name.as_deref()?.as_bytes())?;
    if is_parser_synthesized_query_tag(tag) {
        return None;
    }
    let mut tests = Vec::with_capacity(selector.tests.len());
    for test in &selector.tests {
        tests.push(match test {
            CssSimpleSelector::Id(value) => CompiledTest::Id(value.clone()),
            CssSimpleSelector::Class(value) => CompiledTest::Class(value.clone()),
            CssSimpleSelector::AttributePresent(name) => {
                CompiledTest::AttributePresent(NameKey::from_ascii_casefold(name.as_bytes())?)
            }
            CssSimpleSelector::AttributeEquals(name, value) => CompiledTest::AttributeEquals(
                NameKey::from_ascii_casefold(name.as_bytes())?,
                value.clone(),
            ),
        });
    }
    Some(CompiledCompound { tag, tests })
}

fn compile_xpath(
    path: &super::super::XPathPath,
    _projection: &StreamingProjection,
) -> Option<(CompiledCompound, CompiledCompound, StreamingShape, String)> {
    if !matches!(path.leading_axis, XPathAxis::Descendant) {
        return None;
    }
    match path.steps.as_slice() {
        [root] => {
            let name = xpath_step_name(root)?.to_ascii_lowercase();
            let compiled = compile_xpath_step(root)?;
            Some((compiled.clone(), compiled, StreamingShape::Root, name))
        }
        [left, right] => {
            let shape = match right.axis {
                XPathAxis::Descendant => StreamingShape::Descendant,
                XPathAxis::Child => StreamingShape::Child,
            };
            Some((
                compile_xpath_step(left)?,
                compile_xpath_step(right)?,
                shape,
                xpath_step_name(left)?.to_ascii_lowercase(),
            ))
        }
        _ => None,
    }
}

fn compile_xpath_step(step: &XPathStep) -> Option<CompiledCompound> {
    let tag = NameKey::from_ascii_casefold(xpath_step_name(step)?.as_bytes())?;
    if is_parser_synthesized_query_tag(tag) {
        return None;
    }
    let mut tests = Vec::with_capacity(1);
    if let Some(attribute) = &step.attribute {
        let key = NameKey::from_ascii_casefold(attribute.name.as_bytes())?;
        tests.push(
            attribute
                .value
                .as_ref()
                .map_or(CompiledTest::AttributePresent(key), |value| {
                    CompiledTest::AttributeEquals(key, value.clone())
                }),
        );
    }
    Some(CompiledCompound { tag, tests })
}

const fn is_parser_synthesized_query_tag(tag: NameKey) -> bool {
    matches!(tag, HTML | HEAD | BODY | TBODY | COLGROUP)
}

fn xpath_step_name(step: &XPathStep) -> Option<&str> {
    match &step.name_test {
        XPathNameTest::Named(name) => Some(name),
        XPathNameTest::Any => None,
    }
}

const fn one_element<T>(values: &[T]) -> Option<&T> {
    if values.len() == 1 {
        values.first()
    } else {
        None
    }
}

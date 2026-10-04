mod evaluation;
mod parser;
mod predicate_parser;

pub(super) use parser::{parse, validate_syntax};

#[derive(Clone, Debug)]
pub(super) struct XPath {
    absolute: bool,
    steps: Vec<Step>,
    query_steps: usize,
}

impl XPath {
    pub(super) const fn step_count(&self) -> usize {
        self.query_steps
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Axis {
    Child,
    Descendant,
    SelfNode,
}

#[derive(Clone, Debug)]
struct Step {
    axis: Axis,
    test: NodeTest,
    predicates: Vec<Predicate>,
}

#[derive(Clone, Debug)]
enum NodeTest {
    AnyElement,
    ExpandedName {
        namespace: Option<String>,
        local: String,
    },
}

#[derive(Clone, Debug)]
enum Predicate {
    AttributeExists {
        namespace: Option<String>,
        local: String,
    },
    AttributeEquals {
        namespace: Option<String>,
        local: String,
        value: String,
    },
    LocalNameEquals(String),
    Position(usize),
}

fn is_name_start(character: char) -> bool {
    character == '_' || character.is_alphabetic()
}

fn is_name_character(character: char) -> bool {
    is_name_start(character) || character.is_ascii_digit() || matches!(character, '-' | '.')
}

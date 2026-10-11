use crate::internal::documents::NamespaceBinding;

use super::super::{XmlError, namespace_uri, query_steps_exceeded};
use super::predicate_parser::parse_predicate;
use super::{Axis, NodeTest, Step, XPath, is_name_character, is_name_start};

pub(in crate::internal::documents::xml) fn parse(
    expression: &str,
    bindings: &[NamespaceBinding],
    maximum_steps: u32,
) -> Result<XPath, XmlError> {
    let mut parser = Parser::new(expression, bindings, Some(maximum_steps));
    parser.parse()
}

pub(in crate::internal::documents::xml) fn validate_syntax(
    expression: &str,
    bindings: &[NamespaceBinding],
) -> Result<(), XmlError> {
    let mut parser = Parser::new(expression, bindings, None);
    parser.parse().map(|_| ())
}

struct Parser<'a> {
    characters: Vec<char>,
    position: usize,
    bindings: &'a [NamespaceBinding],
    maximum_steps: Option<u32>,
    steps: usize,
}

impl<'a> Parser<'a> {
    fn new(expression: &str, bindings: &'a [NamespaceBinding], maximum_steps: Option<u32>) -> Self {
        Self {
            characters: expression.chars().collect(),
            position: 0,
            bindings,
            maximum_steps,
            steps: 0,
        }
    }

    fn parse(&mut self) -> Result<XPath, XmlError> {
        self.skip_whitespace();
        let absolute = self.consume('/');
        let first_axis = if absolute && self.consume('/') {
            Axis::Descendant
        } else if absolute {
            Axis::Child
        } else if self.consume('.') {
            if self.consume('/') {
                if self.consume('/') {
                    Axis::Descendant
                } else {
                    Axis::Child
                }
            } else {
                Axis::SelfNode
            }
        } else {
            Axis::Child
        };
        if self.peek().is_none() && first_axis != Axis::SelfNode {
            return Err(XmlError::InvalidQuery);
        }

        let mut steps = Vec::new();
        let mut next_axis = first_axis;
        if next_axis == Axis::SelfNode && self.peek().is_none() {
            steps.push(Step {
                axis: Axis::SelfNode,
                test: NodeTest::AnyElement,
                predicates: Vec::new(),
            });
            return Ok(XPath {
                absolute,
                steps,
                query_steps: self.steps,
            });
        }
        loop {
            self.skip_whitespace();
            steps.push(self.parse_step(next_axis)?);
            self.skip_whitespace();
            if self.peek().is_none() {
                break;
            }
            if !self.consume('/') {
                return Err(XmlError::InvalidQuery);
            }
            next_axis = if self.consume('/') {
                Axis::Descendant
            } else {
                Axis::Child
            };
            if self.peek().is_none() {
                return Err(XmlError::InvalidQuery);
            }
        }
        Ok(XPath {
            absolute,
            steps,
            query_steps: self.steps,
        })
    }

    fn parse_step(&mut self, axis: Axis) -> Result<Step, XmlError> {
        let test = self.parse_node_test()?;
        let mut predicates = Vec::new();
        loop {
            self.skip_whitespace();
            if !self.consume('[') {
                break;
            }
            let source = self.read_predicate()?;
            predicates.push(parse_predicate(&source, self.bindings)?);
            self.count_step()?;
        }
        self.count_step()?;
        Ok(Step {
            axis,
            test,
            predicates,
        })
    }

    fn parse_node_test(&mut self) -> Result<NodeTest, XmlError> {
        if self.consume('*') {
            return Ok(NodeTest::AnyElement);
        }
        let first = self.read_identifier()?;
        if !self.consume(':') {
            return Ok(NodeTest::ExpandedName {
                namespace: None,
                local: first,
            });
        }
        if self.peek() == Some(':') {
            return Err(XmlError::InvalidQuery);
        }
        let local = self.read_identifier()?;
        let namespace = namespace_uri(self.bindings, Some(&first), false)?;
        Ok(NodeTest::ExpandedName { namespace, local })
    }

    fn read_predicate(&mut self) -> Result<String, XmlError> {
        let mut source = String::new();
        let mut quote = None;
        let mut parentheses = 0_u32;
        while let Some(character) = self.next() {
            if let Some(active_quote) = quote {
                source.push(character);
                if character == active_quote {
                    quote = None;
                }
                continue;
            }
            match character {
                '\'' | '"' => {
                    quote = Some(character);
                    source.push(character);
                }
                '(' => {
                    parentheses = parentheses.saturating_add(1);
                    source.push(character);
                }
                ')' => {
                    let Some(value) = parentheses.checked_sub(1) else {
                        return Err(XmlError::InvalidQuery);
                    };
                    parentheses = value;
                    source.push(character);
                }
                ']' if parentheses == 0 => return Ok(source),
                _ => source.push(character),
            }
        }
        Err(XmlError::InvalidQuery)
    }

    fn read_identifier(&mut self) -> Result<String, XmlError> {
        let Some(first) = self.peek() else {
            return Err(XmlError::InvalidQuery);
        };
        if !is_name_start(first) {
            return Err(XmlError::InvalidQuery);
        }
        let mut value = String::new();
        while self.peek().is_some_and(is_name_character) {
            if let Some(character) = self.next() {
                value.push(character);
            }
        }
        Ok(value)
    }

    fn count_step(&mut self) -> Result<(), XmlError> {
        self.steps = self.steps.saturating_add(1);
        if let Some(maximum) = self.maximum_steps {
            let observed = u32::try_from(self.steps).unwrap_or(u32::MAX);
            if observed > maximum {
                return Err(query_steps_exceeded(maximum, self.steps));
            }
        }
        Ok(())
    }

    fn skip_whitespace(&mut self) {
        while self.peek().is_some_and(char::is_whitespace) {
            self.next();
        }
    }

    fn consume(&mut self, expected: char) -> bool {
        if self.peek() == Some(expected) {
            self.next();
            true
        } else {
            false
        }
    }

    fn peek(&self) -> Option<char> {
        self.characters.get(self.position).copied()
    }

    fn next(&mut self) -> Option<char> {
        let character = self.peek()?;
        self.position = self.position.saturating_add(1);
        Some(character)
    }
}

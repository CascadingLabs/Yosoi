mod ast;
mod evaluation;

pub(super) use ast::{
    AttributeTest, Combinator, CompoundSelector, NameTest, NamespaceTest, Selector, SelectorList,
    SimpleCondition,
};

use crate::internal::documents::NamespaceBinding;

use super::{XmlError, namespace_uri};

pub(super) fn parse(
    expression: &str,
    bindings: &[NamespaceBinding],
    maximum_steps: u32,
) -> Result<SelectorList, XmlError> {
    let mut parser = Parser::new(expression, bindings, Some(maximum_steps));
    parser.parse()
}

pub(super) fn validate_syntax(
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

    fn parse(&mut self) -> Result<SelectorList, XmlError> {
        let mut selectors = Vec::new();
        self.skip_whitespace();
        if self.peek().is_none() {
            return Err(XmlError::InvalidQuery);
        }
        loop {
            selectors.push(self.parse_selector()?);
            self.skip_whitespace();
            if self.consume(',') {
                self.skip_whitespace();
                if self.peek().is_none() {
                    return Err(XmlError::InvalidQuery);
                }
            } else if self.peek().is_none() {
                break;
            } else {
                return Err(XmlError::InvalidQuery);
            }
        }
        Ok(SelectorList {
            selectors,
            steps: self.steps,
        })
    }

    fn parse_selector(&mut self) -> Result<Selector, XmlError> {
        let mut compounds = vec![self.parse_compound()?];
        let mut combinators = Vec::new();
        loop {
            let had_space = self.skip_whitespace();
            if self.peek().is_none() || self.peek() == Some(',') {
                break;
            }
            let combinator = if self.consume('>') {
                self.skip_whitespace();
                Combinator::Child
            } else if had_space {
                Combinator::Descendant
            } else {
                return Err(XmlError::InvalidQuery);
            };
            self.count_step()?;
            if self.peek().is_none() || self.peek() == Some(',') || self.peek() == Some('>') {
                return Err(XmlError::InvalidQuery);
            }
            combinators.push(combinator);
            compounds.push(self.parse_compound()?);
        }
        if compounds.len() != combinators.len().saturating_add(1) {
            return Err(XmlError::InvalidQuery);
        }
        Ok(Selector {
            compounds,
            combinators,
        })
    }

    fn parse_compound(&mut self) -> Result<CompoundSelector, XmlError> {
        let name = self.parse_optional_element_name()?;
        let mut conditions = Vec::new();
        loop {
            match self.peek() {
                Some('#') => {
                    self.next();
                    conditions.push(SimpleCondition::Id(self.read_identifier()?));
                    self.count_step()?;
                }
                Some('.') => {
                    self.next();
                    conditions.push(SimpleCondition::Class(self.read_identifier()?));
                    self.count_step()?;
                }
                Some('[') => {
                    conditions.push(SimpleCondition::Attribute(self.parse_attribute()?));
                    self.count_step()?;
                }
                Some(':') => {
                    self.next();
                    if self.read_identifier()? != "first-child" {
                        return Err(XmlError::InvalidQuery);
                    }
                    conditions.push(SimpleCondition::FirstChild);
                    self.count_step()?;
                }
                _ => break,
            }
        }
        if name.is_none() && conditions.is_empty() {
            return Err(XmlError::InvalidQuery);
        }
        self.count_step()?;
        Ok(CompoundSelector { name, conditions })
    }

    fn parse_optional_element_name(&mut self) -> Result<Option<NameTest>, XmlError> {
        match self.peek() {
            Some('*') => {
                self.next();
                if self.is_namespace_separator() {
                    self.next();
                    let local_name = self.read_optional_wildcard_name()?;
                    Ok(Some(NameTest {
                        namespace: NamespaceTest::Any,
                        local_name,
                    }))
                } else {
                    Ok(Some(NameTest {
                        namespace: self.default_namespace(true)?,
                        local_name: None,
                    }))
                }
            }
            Some('|') => {
                self.next();
                let local_name = self.read_optional_wildcard_name()?;
                Ok(Some(NameTest {
                    namespace: NamespaceTest::None,
                    local_name,
                }))
            }
            Some(character) if is_name_start(character) => {
                let first = self.read_identifier()?;
                if self.is_namespace_separator() {
                    self.next();
                    let namespace = self.bound_namespace(&first)?;
                    let local_name = self.read_optional_wildcard_name()?;
                    Ok(Some(NameTest {
                        namespace,
                        local_name,
                    }))
                } else {
                    Ok(Some(NameTest {
                        namespace: self.default_namespace(true)?,
                        local_name: Some(first),
                    }))
                }
            }
            _ => Ok(None),
        }
    }

    fn parse_attribute(&mut self) -> Result<AttributeTest, XmlError> {
        if !self.consume('[') {
            return Err(XmlError::InvalidQuery);
        }
        self.skip_whitespace();
        let name = self.parse_attribute_name()?;
        self.skip_whitespace();
        let value = if self.consume('=') {
            self.skip_whitespace();
            Some(self.read_attribute_value()?)
        } else {
            None
        };
        self.skip_whitespace();
        if !self.consume(']') {
            return Err(XmlError::InvalidQuery);
        }
        Ok(AttributeTest { name, value })
    }

    fn parse_attribute_name(&mut self) -> Result<NameTest, XmlError> {
        let first = match self.peek() {
            Some('*') => {
                self.next();
                "*".to_owned()
            }
            Some('|') => String::new(),
            Some(character) if is_name_start(character) => self.read_identifier()?,
            _ => return Err(XmlError::InvalidQuery),
        };
        if self.is_namespace_separator() {
            self.next();
            let namespace = if first.is_empty() {
                NamespaceTest::None
            } else if first == "*" {
                NamespaceTest::Any
            } else {
                self.bound_namespace(&first)?
            };
            let local_name = self.read_identifier()?;
            return Ok(NameTest {
                namespace,
                local_name: Some(local_name),
            });
        }
        if first.is_empty() {
            return Err(XmlError::InvalidQuery);
        }
        Ok(NameTest {
            namespace: NamespaceTest::None,
            local_name: Some(first),
        })
    }

    fn read_attribute_value(&mut self) -> Result<String, XmlError> {
        match self.peek() {
            Some(quote @ ('\'' | '"')) => {
                self.next();
                let mut value = String::new();
                loop {
                    match self.next() {
                        Some(character) if character == quote => return Ok(value),
                        Some('\\') | None => return Err(XmlError::InvalidQuery),
                        Some(character) => value.push(character),
                    }
                }
            }
            Some(character) if is_name_character(character) => self.read_identifier(),
            _ => Err(XmlError::InvalidQuery),
        }
    }

    fn read_optional_wildcard_name(&mut self) -> Result<Option<String>, XmlError> {
        if self.consume('*') {
            Ok(None)
        } else {
            self.read_identifier().map(Some)
        }
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

    fn is_namespace_separator(&self) -> bool {
        self.peek() == Some('|') && self.peek_next() != Some('=')
    }

    fn bound_namespace(&self, prefix: &str) -> Result<NamespaceTest, XmlError> {
        let uri = namespace_uri(self.bindings, Some(prefix), false)?
            .ok_or(XmlError::UnboundNamespacePrefix)?;
        Ok(NamespaceTest::Uri(uri))
    }

    fn default_namespace(&self, elements: bool) -> Result<NamespaceTest, XmlError> {
        let uri = namespace_uri(self.bindings, None, elements)?;
        Ok(match uri {
            Some(value) => NamespaceTest::Uri(value),
            None if elements => NamespaceTest::Any,
            None => NamespaceTest::None,
        })
    }

    fn count_step(&mut self) -> Result<(), XmlError> {
        self.steps = self.steps.saturating_add(1);
        if let Some(maximum) = self.maximum_steps {
            let observed = u32::try_from(self.steps).unwrap_or(u32::MAX);
            if observed > maximum {
                return Err(super::query_steps_exceeded(maximum, self.steps));
            }
        }
        Ok(())
    }

    fn skip_whitespace(&mut self) -> bool {
        let mut found = false;
        while self.peek().is_some_and(char::is_whitespace) {
            self.next();
            found = true;
        }
        found
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

    fn peek_next(&self) -> Option<char> {
        self.position
            .checked_add(1)
            .and_then(|index| self.characters.get(index))
            .copied()
    }

    fn next(&mut self) -> Option<char> {
        let character = self.peek()?;
        self.position = self.position.saturating_add(1);
        Some(character)
    }
}

fn is_name_start(character: char) -> bool {
    character == '_' || character.is_alphabetic()
}

fn is_name_character(character: char) -> bool {
    is_name_start(character) || character.is_ascii_digit() || matches!(character, '-' | '.')
}

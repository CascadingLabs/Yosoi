use crate::NamespaceBinding;

use super::super::{XmlError, namespace_uri};
use super::{Predicate, is_name_character, is_name_start};

pub(super) fn parse_predicate(
    source: &str,
    bindings: &[NamespaceBinding],
) -> Result<Predicate, XmlError> {
    let mut parser = PredicateParser::new(source, bindings);
    parser.parse()
}

struct PredicateParser<'a> {
    characters: Vec<char>,
    position: usize,
    bindings: &'a [NamespaceBinding],
}

impl<'a> PredicateParser<'a> {
    fn new(source: &str, bindings: &'a [NamespaceBinding]) -> Self {
        Self {
            characters: source.chars().collect(),
            position: 0,
            bindings,
        }
    }

    fn parse(&mut self) -> Result<Predicate, XmlError> {
        self.skip_whitespace();
        if self
            .peek()
            .is_some_and(|character| character.is_ascii_digit())
        {
            let position = self
                .read_digits()?
                .parse::<usize>()
                .map_err(|_| XmlError::InvalidQuery)?;
            self.skip_whitespace();
            if position == 0 || self.peek().is_some() {
                return Err(XmlError::InvalidQuery);
            }
            return Ok(Predicate::Position(position));
        }
        if self.consume('@') {
            return self.parse_attribute_predicate();
        }
        if self.read_identifier()? != "local-name" || !self.consume('(') {
            return Err(XmlError::InvalidQuery);
        }
        self.skip_whitespace();
        if self.consume('.') {
            self.skip_whitespace();
        }
        if !self.consume(')') {
            return Err(XmlError::InvalidQuery);
        }
        self.skip_whitespace();
        if !self.consume('=') {
            return Err(XmlError::InvalidQuery);
        }
        self.skip_whitespace();
        let value = self.read_string_literal()?;
        self.skip_whitespace();
        if self.peek().is_some() {
            return Err(XmlError::InvalidQuery);
        }
        Ok(Predicate::LocalNameEquals(value))
    }

    fn parse_attribute_predicate(&mut self) -> Result<Predicate, XmlError> {
        let (namespace, local) = self.read_qname()?;
        self.skip_whitespace();
        if self.consume('=') {
            self.skip_whitespace();
            let value = self.read_string_literal()?;
            self.skip_whitespace();
            if self.peek().is_some() {
                return Err(XmlError::InvalidQuery);
            }
            Ok(Predicate::AttributeEquals {
                namespace,
                local,
                value,
            })
        } else if self.peek().is_none() {
            Ok(Predicate::AttributeExists { namespace, local })
        } else {
            Err(XmlError::InvalidQuery)
        }
    }

    fn read_qname(&mut self) -> Result<(Option<String>, String), XmlError> {
        let first = self.read_identifier()?;
        if !self.consume(':') {
            return Ok((None, first));
        }
        if self.peek() == Some(':') {
            return Err(XmlError::InvalidQuery);
        }
        let local = self.read_identifier()?;
        let namespace = namespace_uri(self.bindings, Some(&first), false)?;
        Ok((namespace, local))
    }

    fn read_string_literal(&mut self) -> Result<String, XmlError> {
        let Some(quote @ ('\'' | '"')) = self.next() else {
            return Err(XmlError::InvalidQuery);
        };
        let mut value = String::new();
        loop {
            match self.next() {
                Some(character) if character == quote => return Ok(value),
                Some(character) => value.push(character),
                None => return Err(XmlError::InvalidQuery),
            }
        }
    }

    fn read_digits(&mut self) -> Result<String, XmlError> {
        let mut digits = String::new();
        while self
            .peek()
            .is_some_and(|character| character.is_ascii_digit())
        {
            if let Some(digit) = self.next() {
                digits.push(digit);
            }
        }
        if digits.is_empty() {
            Err(XmlError::InvalidQuery)
        } else {
            Ok(digits)
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

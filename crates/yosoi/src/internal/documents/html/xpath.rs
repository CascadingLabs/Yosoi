use std::{iter::Peekable, str::Chars};

use crate::internal::documents::LocateFailure;

use super::{
    SelectorElement, SelectorVisitBudget, element_attribute, element_name_matches,
    is_name_character, is_name_start,
};

const MAX_XPATH_STEPS: usize = 32;

#[derive(Clone)]
pub struct XPathPath {
    pub(in crate::internal::documents) steps: Vec<XPathStep>,
    pub(in crate::internal::documents) leading_axis: XPathAxis,
    pub(in crate::internal::documents) step_count: u64,
}

#[derive(Clone)]
pub struct XPathStep {
    pub(in crate::internal::documents) axis: XPathAxis,
    pub(in crate::internal::documents) name_test: XPathNameTest,
    pub(in crate::internal::documents) attribute: Option<XPathAttributeTest>,
}

#[derive(Clone, Copy)]
pub enum XPathAxis {
    Child,
    Descendant,
}

#[derive(Clone)]
pub enum XPathNameTest {
    Any,
    Named(String),
}

#[derive(Clone)]
pub struct XPathAttributeTest {
    pub(in crate::internal::documents) name: String,
    pub(in crate::internal::documents) value: Option<String>,
}

struct XPathParser<'a> {
    chars: Peekable<Chars<'a>>,
    step_count: u64,
}

pub fn parse_xpath(expression: &str) -> Result<XPathPath, ()> {
    let mut parser = XPathParser {
        chars: expression.chars().peekable(),
        step_count: 0,
    };
    parser.skip_space();
    let mut leading_axis = XPathAxis::Child;
    match parser.peek() {
        Some('/') => {
            parser.next();
            if parser.peek() == Some('/') {
                parser.next();
                leading_axis = XPathAxis::Descendant;
            }
        }
        Some('.') => {
            parser.next();
            if parser.next() != Some('/') {
                return Err(());
            }
            if parser.peek() == Some('/') {
                parser.next();
                leading_axis = XPathAxis::Descendant;
            }
        }
        _ => {}
    }
    parser.skip_space();
    let mut steps = vec![parser.parse_step(leading_axis)?];
    while {
        parser.skip_space();
        parser.peek().is_some()
    } {
        if parser.next() != Some('/') {
            return Err(());
        }
        let axis = if parser.peek() == Some('/') {
            parser.next();
            XPathAxis::Descendant
        } else {
            XPathAxis::Child
        };
        parser.skip_space();
        steps.push(parser.parse_step(axis)?);
        if steps.len() > MAX_XPATH_STEPS {
            return Err(());
        }
    }
    Ok(XPathPath {
        steps,
        leading_axis,
        step_count: parser.step_count,
    })
}

impl XPathParser<'_> {
    fn parse_step(&mut self, axis: XPathAxis) -> Result<XPathStep, ()> {
        self.step_count = self.step_count.checked_add(1).ok_or(())?;
        let name_test = if self.peek() == Some('*') {
            self.next();
            XPathNameTest::Any
        } else {
            XPathNameTest::Named(self.read_name()?)
        };
        self.skip_space();
        let attribute = if self.peek() == Some('[') {
            self.parse_attribute_predicate()?
        } else {
            None
        };
        Ok(XPathStep {
            axis,
            name_test,
            attribute,
        })
    }

    fn parse_attribute_predicate(&mut self) -> Result<Option<XPathAttributeTest>, ()> {
        if self.next() != Some('[') {
            return Err(());
        }
        self.skip_space();
        if self.next() != Some('@') {
            return Err(());
        }
        let name = self.read_name()?;
        self.skip_space();
        let value = if self.peek() == Some('=') {
            self.next();
            self.skip_space();
            Some(self.read_quoted_value()?)
        } else {
            None
        };
        self.skip_space();
        if self.next() != Some(']') {
            return Err(());
        }
        Ok(Some(XPathAttributeTest { name, value }))
    }

    fn read_quoted_value(&mut self) -> Result<String, ()> {
        let quote = match self.next() {
            Some('\'') => '\'',
            Some('"') => '"',
            _ => return Err(()),
        };
        let mut value = String::new();
        loop {
            match self.next() {
                Some(character) if character == quote => return Ok(value),
                Some('\\' | '\0') | None => return Err(()),
                Some(character) => value.push(character),
            }
        }
    }

    fn read_name(&mut self) -> Result<String, ()> {
        let mut name = String::new();
        while self.peek().is_some_and(is_name_character) {
            if let Some(character) = self.next() {
                name.push(character);
            }
        }
        if name.is_empty() || !name.chars().next().is_some_and(is_name_start) {
            Err(())
        } else {
            Ok(name)
        }
    }

    fn skip_space(&mut self) {
        while self
            .peek()
            .is_some_and(|character| character.is_ascii_whitespace())
        {
            self.next();
        }
    }

    fn peek(&mut self) -> Option<char> {
        self.chars.peek().copied()
    }

    fn next(&mut self) -> Option<char> {
        self.chars.next()
    }
}

pub fn xpath_step_matches<E: SelectorElement>(
    element: &E,
    step: &XPathStep,
    budget: &mut SelectorVisitBudget,
) -> Result<bool, LocateFailure> {
    let name_matches = match &step.name_test {
        XPathNameTest::Any => true,
        XPathNameTest::Named(expected) => element_name_matches(element, expected),
    };
    if !name_matches {
        return Ok(false);
    }
    match &step.attribute {
        None => Ok(true),
        Some(test) => {
            budget.charge()?;
            match (element_attribute(element, &test.name, budget)?, &test.value) {
                (Some(_), None) => Ok(true),
                (Some(actual), Some(expected)) => Ok(actual == *expected),
                (None, _) => Ok(false),
            }
        }
    }
}

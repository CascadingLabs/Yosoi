use std::{iter::Peekable, str::Chars};

use crate::LocateFailure;

use super::{SelectorElement, SelectorVisitBudget, element_attribute, element_name_matches};

const MAX_CSS_GROUPS: usize = 16;
const MAX_SELECTOR_COMPONENTS: usize = 64;

#[derive(Clone)]
pub struct CssSelectorList {
    pub(crate) groups: Vec<CssComplexSelector>,
    pub(crate) step_count: u64,
}

#[derive(Clone)]
pub struct CssComplexSelector {
    pub(crate) steps: Vec<CssSelectorStep>,
}

#[derive(Clone)]
pub struct CssSelectorStep {
    pub(crate) relation: Option<Combinator>,
    pub(crate) compound: CssCompoundSelector,
}

#[derive(Clone, Copy)]
pub enum Combinator {
    Child,
    Descendant,
}

#[derive(Clone)]
pub struct CssCompoundSelector {
    pub(crate) tag_name: Option<String>,
    pub(crate) tests: Vec<CssSimpleSelector>,
}

#[derive(Clone)]
pub enum CssSimpleSelector {
    Id(String),
    Class(String),
    AttributePresent(String),
    AttributeEquals(String, String),
}

struct CssParser<'a> {
    chars: Peekable<Chars<'a>>,
    component_count: usize,
    step_count: u64,
}

pub fn parse_css(expression: &str) -> Result<CssSelectorList, ()> {
    let mut parser = CssParser {
        chars: expression.chars().peekable(),
        component_count: 0,
        step_count: 0,
    };
    parser.skip_space();
    let mut groups = Vec::new();
    loop {
        if groups.len() >= MAX_CSS_GROUPS {
            return Err(());
        }
        groups.push(parser.parse_complex_selector()?);
        parser.skip_space();
        match parser.peek() {
            Some(',') => {
                parser.next();
                parser.skip_space();
                if parser.peek().is_none() {
                    return Err(());
                }
            }
            None => break,
            Some(_) => return Err(()),
        }
    }
    Ok(CssSelectorList {
        groups,
        step_count: parser.step_count,
    })
}

impl CssParser<'_> {
    fn parse_complex_selector(&mut self) -> Result<CssComplexSelector, ()> {
        let mut steps = vec![CssSelectorStep {
            relation: None,
            compound: self.parse_compound_selector()?,
        }];
        loop {
            let separated_by_space = self.skip_space();
            match self.peek() {
                Some('>') => {
                    self.next();
                    self.skip_space();
                    self.add_step()?;
                    steps.push(CssSelectorStep {
                        relation: Some(Combinator::Child),
                        compound: self.parse_compound_selector()?,
                    });
                }
                Some(',') | None => break,
                Some(_) if separated_by_space => {
                    self.add_step()?;
                    steps.push(CssSelectorStep {
                        relation: Some(Combinator::Descendant),
                        compound: self.parse_compound_selector()?,
                    });
                }
                Some(_) => return Err(()),
            }
            if steps.len() > MAX_SELECTOR_COMPONENTS {
                return Err(());
            }
        }
        Ok(CssComplexSelector { steps })
    }

    fn parse_compound_selector(&mut self) -> Result<CssCompoundSelector, ()> {
        let tag_name = match self.peek() {
            Some('*') => {
                self.next();
                self.add_component()?;
                Some("*".to_owned())
            }
            Some(character) if is_name_start(character) => {
                let name = self.read_name()?;
                self.add_component()?;
                Some(name)
            }
            _ => None,
        };
        let mut tests = Vec::new();
        loop {
            let test = match self.peek() {
                Some('#') => {
                    self.next();
                    CssSimpleSelector::Id(self.read_identifier()?.clone())
                }
                Some('.') => {
                    self.next();
                    CssSimpleSelector::Class(self.read_identifier()?.clone())
                }
                Some('[') => self.parse_attribute_selector()?,
                _ => break,
            };
            self.add_component()?;
            tests.push(test);
        }
        if tag_name.is_none() && tests.is_empty() {
            return Err(());
        }
        Ok(CssCompoundSelector { tag_name, tests })
    }

    fn parse_attribute_selector(&mut self) -> Result<CssSimpleSelector, ()> {
        if self.next() != Some('[') {
            return Err(());
        }
        self.skip_space();
        let name = self.read_name()?;
        self.skip_space();
        if self.peek() == Some(']') {
            self.next();
            return Ok(CssSimpleSelector::AttributePresent(name));
        }
        if self.next() != Some('=') {
            return Err(());
        }
        self.skip_space();
        let value = self.read_quoted_value()?;
        self.skip_space();
        if self.next() != Some(']') {
            return Err(());
        }
        Ok(CssSimpleSelector::AttributeEquals(name, value))
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

    fn read_identifier(&mut self) -> Result<String, ()> {
        let mut value = String::new();
        while self.peek().is_some_and(is_name_character) {
            if let Some(character) = self.next() {
                value.push(character);
            }
        }
        if value.is_empty() { Err(()) } else { Ok(value) }
    }

    fn add_component(&mut self) -> Result<(), ()> {
        self.component_count = self.component_count.checked_add(1).ok_or(())?;
        self.step_count = self.step_count.checked_add(1).ok_or(())?;
        if self.component_count > MAX_SELECTOR_COMPONENTS {
            return Err(());
        }
        Ok(())
    }

    fn add_step(&mut self) -> Result<(), ()> {
        self.component_count = self.component_count.checked_add(1).ok_or(())?;
        self.step_count = self.step_count.checked_add(1).ok_or(())?;
        if self.component_count > MAX_SELECTOR_COMPONENTS {
            return Err(());
        }
        Ok(())
    }

    fn skip_space(&mut self) -> bool {
        let mut skipped = false;
        while self
            .peek()
            .is_some_and(|character| character.is_ascii_whitespace())
        {
            self.next();
            skipped = true;
        }
        skipped
    }

    fn peek(&mut self) -> Option<char> {
        self.chars.peek().copied()
    }

    fn next(&mut self) -> Option<char> {
        self.chars.next()
    }
}

pub const fn is_name_start(character: char) -> bool {
    character.is_ascii_alphabetic() || character == '_'
}

pub const fn is_name_character(character: char) -> bool {
    character.is_ascii_alphanumeric() || matches!(character, '_' | '-')
}

pub fn compound_matches<E: SelectorElement>(
    element: &E,
    selector: &CssCompoundSelector,
    budget: &mut SelectorVisitBudget,
) -> Result<bool, LocateFailure> {
    if let Some(tag_name) = &selector.tag_name
        && tag_name != "*"
        && !element_name_matches(element, tag_name)
    {
        return Ok(false);
    }
    for test in &selector.tests {
        budget.charge()?;
        let matches = match test {
            CssSimpleSelector::Id(expected) => {
                element_attribute(element, "id", budget)?.is_some_and(|value| value == *expected)
            }
            CssSimpleSelector::Class(expected) => element_attribute(element, "class", budget)?
                .is_some_and(|value| {
                    value
                        .split_ascii_whitespace()
                        .any(|class| class == expected)
                }),
            CssSimpleSelector::AttributePresent(name) => {
                element_attribute(element, name, budget)?.is_some()
            }
            CssSimpleSelector::AttributeEquals(name, expected) => {
                element_attribute(element, name, budget)?.is_some_and(|value| value == *expected)
            }
        };
        if !matches {
            return Ok(false);
        }
    }
    Ok(true)
}

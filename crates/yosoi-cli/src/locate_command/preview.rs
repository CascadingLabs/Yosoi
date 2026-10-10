//! Bounded, terminal-safe finding previews; JSON output retains complete values.

use std::{borrow::Cow, io::Write};

use anyhow::{Context as _, Result};
use clap::builder::styling::Style;
use unicode_width::UnicodeWidthChar as _;
use yosoi::locators::ProjectedValue;

use crate::presentation::Theme;

pub(super) const MAX_FINDINGS: usize = 10;
const MAX_CHARACTERS: usize = 600;
const LINE_COLUMNS: usize = 92;

pub(super) fn value(
    output: &mut impl Write,
    projected: &ProjectedValue,
    full: bool,
    theme: Theme,
) -> Result<()> {
    let (kind, text) = match projected {
        ProjectedValue::Text(text) => ("text", Cow::Borrowed(text.as_str())),
        ProjectedValue::Json(value) => (
            "json",
            Cow::Owned(
                serde_json::to_string_pretty(value).context("could not render JSON finding")?,
            ),
        ),
        other => {
            let kind = match other {
                ProjectedValue::TextWithCaptures { .. } => "text with captures",
                ProjectedValue::Attribute { .. } => "attribute",
                ProjectedValue::Node(_) => "node",
                _ => "value",
            };
            (
                kind,
                Cow::Owned(
                    serde_json::to_string_pretty(other).context("could not render finding")?,
                ),
            )
        }
    };
    let muted = theme.muted;
    writeln!(output, "{muted}({kind}){muted:#}")?;
    let total = text.chars().count();
    let limit = if full { total } else { MAX_CHARACTERS };
    let visible: String = text
        .chars()
        .take(limit)
        .map(|character| {
            if character.is_control() && character != '\n' {
                ' '
            } else {
                character
            }
        })
        .collect();
    wrapped(output, &visible, theme.value)?;
    if total > limit {
        writeln!(
            output,
            "    {muted}[preview: {limit} of {total} characters; use --full or --json]{muted:#}"
        )?;
    }
    Ok(())
}

fn wrapped(output: &mut impl Write, text: &str, style: Style) -> Result<()> {
    if text.is_empty() {
        writeln!(output, "    (empty)")?;
        return Ok(());
    }
    for paragraph in text.split('\n') {
        write!(output, "    {style}")?;
        let mut columns = 0_usize;
        for word in paragraph.split_whitespace() {
            if columns > 0 {
                if columns.saturating_add(1).saturating_add(
                    word.chars()
                        .map(|character| character.width().unwrap_or(0))
                        .fold(0_usize, usize::saturating_add),
                ) > LINE_COLUMNS
                {
                    write!(output, "{style:#}\n    {style}")?;
                    columns = 0;
                } else {
                    write!(output, " ")?;
                    columns = columns.saturating_add(1);
                }
            }
            for character in word.chars() {
                let width = character.width().unwrap_or(0);
                if columns > 0 && columns.saturating_add(width) > LINE_COLUMNS {
                    write!(output, "{style:#}\n    {style}")?;
                    columns = 0;
                }
                write!(output, "{character}")?;
                columns = columns.saturating_add(width);
            }
        }
        writeln!(output, "{style:#}")?;
    }
    Ok(())
}

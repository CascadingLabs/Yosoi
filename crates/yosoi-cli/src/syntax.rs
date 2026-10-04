//! Case-insensitive normalization for command and option syntax.
//!
//! Values are copied verbatim. Only ASCII command and option spellings are
//! folded, and only when they match an entry in the supplied Clap command.

use std::{
    error::Error,
    ffi::{OsStr, OsString},
    fmt::{self, Display, Formatter},
    ptr, str,
};

use clap::{Arg, ArgAction, Command};

mod validate;

/// A syntax shape that this normalizer cannot safely interpret.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SyntaxError {
    /// Two known spellings collide under ASCII case folding.
    CaseFoldCollision(String),
    /// A known option accepts an arity this normalizer cannot model.
    UnsupportedArity(String),
    /// A command mixes positional arguments and subcommands.
    AmbiguousPositionals(String),
    /// A parent command has built-in settings that Clap propagates to children.
    UnsupportedBuiltinInheritance(String),
    /// Version propagation cannot be interpreted from raw child command metadata.
    PropagatedVersionWithSubcommands(String),
    /// An option token contains attached non-UTF-8 bytes.
    NonUtf8OptionToken,
}

impl Display for SyntaxError {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::CaseFoldCollision(name) => write!(f, "case-folded CLI syntax collision: {name}"),
            Self::UnsupportedArity(name) => {
                write!(f, "unsupported value arity for CLI option: {name}")
            }
            Self::AmbiguousPositionals(name) => {
                write!(f, "command has both positionals and subcommands: {name}")
            }
            Self::UnsupportedBuiltinInheritance(name) => write!(
                f,
                "cannot normalize child built-in syntax when parent settings are disabled: {name}"
            ),
            Self::PropagatedVersionWithSubcommands(name) => write!(
                f,
                "cannot normalize propagated version settings with subcommands: {name}"
            ),
            Self::NonUtf8OptionToken => write!(
                f,
                "cannot normalize an option with attached non-UTF-8 bytes; pass the value separately"
            ),
        }
    }
}

impl Error for SyntaxError {}

/// Normalize known command and option names while preserving all values.
pub fn normalize_args(
    command: &Command,
    args: impl IntoIterator<Item = OsString>,
) -> Result<Vec<OsString>, SyntaxError> {
    validate::validate_tree(command, &[])?;
    let mut output = Vec::new();
    let mut current = command;
    let mut globals: Vec<&Arg> = Vec::new();
    let mut pending_value = false;
    let mut options_done = false;

    for arg in args {
        if pending_value {
            if arg == "--" {
                options_done = true;
            }
            output.push(arg);
            pending_value = false;
            continue;
        }
        if options_done {
            output.push(arg);
            continue;
        }
        let Some(text) = arg.to_str() else {
            if has_non_utf8_option_token(&arg, current, &globals) {
                return Err(SyntaxError::NonUtf8OptionToken);
            }
            output.push(arg);
            continue;
        };
        if text == "--" {
            output.push(arg);
            options_done = true;
            continue;
        }

        if let Some(body) = text.strip_prefix("--").filter(|body| !body.is_empty()) {
            let (name, value) = body
                .split_once('=')
                .map_or((body, None), |(n, v)| (n, Some(v)));
            let normalized = normalize_long(current, &globals, name)?;
            if let Some((canonical, takes_value)) = normalized {
                let mut token = format!("--{canonical}");
                if let Some(value) = value {
                    token.push('=');
                    token.push_str(value);
                } else if takes_value {
                    pending_value = true;
                }
                output.push(OsString::from(token));
            } else {
                output.push(arg);
            }
            continue;
        }

        if text.starts_with('-') && text.len() > 1 && text != "-" {
            let normalized = normalize_short(current, &globals, text)?;
            match normalized {
                Some((token, takes_value)) => {
                    output.push(OsString::from(token));
                    pending_value = takes_value;
                }
                None => output.push(arg),
            }
            continue;
        }

        if let Some(subcommand) = find_subcommand(current, text) {
            output.push(OsString::from(subcommand.get_name()));
            globals.extend(current.get_arguments().filter(|arg| arg.is_global_set()));
            current = subcommand;
        } else if current.has_subcommands()
            && !current.is_disable_help_subcommand_set()
            && text.eq_ignore_ascii_case("help")
        {
            output.push(OsString::from("help"));
        } else {
            output.push(arg);
        }
    }
    Ok(output)
}

fn normalize_long(
    command: &Command,
    globals: &[&Arg],
    name: &str,
) -> Result<Option<(String, bool)>, SyntaxError> {
    let mut found: Option<(String, bool)> = None;
    for arg in active_args(command, globals) {
        if arg.is_positional() {
            continue;
        }
        let Some(long) = arg.get_long() else {
            continue;
        };
        let aliases = arg.get_all_aliases().unwrap_or_default();
        if long.eq_ignore_ascii_case(name)
            || aliases.iter().any(|alias| alias.eq_ignore_ascii_case(name))
        {
            let value = takes_one_value(arg)?;
            insert_unique(&mut found, long.to_owned(), value)?;
        }
    }
    if !command.is_disable_help_flag_set() && "help".eq_ignore_ascii_case(name) {
        insert_unique(&mut found, "help".to_owned(), false)?;
    }
    if command.get_version().is_some()
        && !command.is_disable_version_flag_set()
        && "version".eq_ignore_ascii_case(name)
    {
        insert_unique(&mut found, "version".to_owned(), false)?;
    }
    Ok(found)
}

fn normalize_short(
    command: &Command,
    globals: &[&Arg],
    token: &str,
) -> Result<Option<(String, bool)>, SyntaxError> {
    let Some(body) = token.strip_prefix('-') else {
        return Ok(None);
    };
    let mut normalized = String::from("-");
    let mut matched = false;
    for (offset, ch) in body.char_indices() {
        let (canonical, takes_value) = match_short(command, globals, ch)?;
        let Some(canonical) = canonical else {
            return Ok(None);
        };
        matched = true;
        normalized.push(canonical);
        if takes_value {
            let tail_start = offset
                .checked_add(ch.len_utf8())
                .ok_or_else(|| SyntaxError::UnsupportedArity(token.to_owned()))?;
            let tail = body
                .get(tail_start..)
                .ok_or_else(|| SyntaxError::UnsupportedArity(token.to_owned()))?;
            normalized.push_str(tail);
            return Ok(Some((normalized, tail.is_empty())));
        }
    }
    Ok(matched.then_some((normalized, false)))
}

fn match_short(
    command: &Command,
    globals: &[&Arg],
    short: char,
) -> Result<(Option<char>, bool), SyntaxError> {
    let mut found = None;
    for arg in active_args(command, globals) {
        if arg.is_positional() {
            continue;
        }
        if let Some(candidate) = arg
            .get_all_short_aliases()
            .unwrap_or_default()
            .into_iter()
            .chain(arg.get_short())
            .find(|candidate| candidate.eq_ignore_ascii_case(&short))
        {
            insert_short(
                &mut found,
                arg.get_short().unwrap_or(candidate),
                takes_one_value(arg)?,
            )?;
        }
    }
    if !command.is_disable_help_flag_set() && short.eq_ignore_ascii_case(&'h') {
        insert_short(&mut found, 'h', false)?;
    }
    if command.get_version().is_some()
        && !command.is_disable_version_flag_set()
        && short.eq_ignore_ascii_case(&'V')
    {
        insert_short(&mut found, 'V', false)?;
    }
    Ok(found.map_or((None, false), |(c, v)| (Some(c), v)))
}

fn active_args<'a>(command: &'a Command, globals: &[&'a Arg]) -> Vec<&'a Arg> {
    let mut args: Vec<&Arg> = command.get_arguments().collect();
    for global in globals.iter().copied() {
        if !args.iter().any(|arg| ptr::eq(*arg, global)) {
            args.push(global);
        }
    }
    args
}

fn takes_one_value(arg: &Arg) -> Result<bool, SyntaxError> {
    match arg.get_action() {
        ArgAction::Set | ArgAction::Append => {
            let range = arg.get_num_args();
            if range.is_some_and(|range| range.min_values() != 1 || range.max_values() != 1) {
                return Err(SyntaxError::UnsupportedArity(arg.get_id().to_string()));
            }
            Ok(true)
        }
        _ => Ok(false),
    }
}

fn has_non_utf8_option_token(arg: &OsStr, command: &Command, globals: &[&Arg]) -> bool {
    let bytes = arg.as_encoded_bytes();
    let Err(error) = str::from_utf8(bytes) else {
        return false;
    };
    let Some(prefix) = bytes
        .get(..error.valid_up_to())
        .and_then(|bytes| str::from_utf8(bytes).ok())
    else {
        return false;
    };
    if let Some(body) = prefix.strip_prefix("--") {
        let Some((name, _)) = body.split_once('=') else {
            return false;
        };
        return normalize_long(command, globals, name)
            .ok()
            .flatten()
            .is_some();
    }
    if !prefix.starts_with('-') {
        return false;
    }
    normalize_short(command, globals, prefix)
        .ok()
        .flatten()
        .is_some()
}

fn find_subcommand<'a>(command: &'a Command, name: &str) -> Option<&'a Command> {
    command.get_subcommands().find(|subcommand| {
        subcommand.get_name().eq_ignore_ascii_case(name)
            || subcommand
                .get_all_aliases()
                .any(|alias| alias.eq_ignore_ascii_case(name))
    })
}

fn insert_unique(
    found: &mut Option<(String, bool)>,
    name: String,
    takes_value: bool,
) -> Result<(), SyntaxError> {
    if found.is_some() {
        return Err(SyntaxError::CaseFoldCollision(name));
    }
    *found = Some((name, takes_value));
    Ok(())
}

fn insert_short(
    found: &mut Option<(char, bool)>,
    short: char,
    takes_value: bool,
) -> Result<(), SyntaxError> {
    if found.is_some() {
        return Err(SyntaxError::CaseFoldCollision(short.to_string()));
    }
    *found = Some((short, takes_value));
    Ok(())
}

#[cfg(test)]
mod tests;

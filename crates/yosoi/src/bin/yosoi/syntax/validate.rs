use std::{iter, ptr};

use clap::{Arg, ArgAction, Command};

use super::SyntaxError;

fn check_arity(arg: &Arg) -> Result<(), SyntaxError> {
    match arg.get_action() {
        ArgAction::Set | ArgAction::Append => {
            let range = arg.get_num_args();
            if range.is_some_and(|range| range.min_values() != 1 || range.max_values() != 1) {
                return Err(SyntaxError::UnsupportedArity(arg.get_id().to_string()));
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

pub(super) fn validate_tree(
    command: &Command,
    inherited_globals: &[&Arg],
) -> Result<(), SyntaxError> {
    let local_args: Vec<&Arg> = command.get_arguments().collect();
    if command.has_subcommands() {
        let version_replaced = local_args.iter().any(|arg| {
            arg.get_long() == Some("version")
                && matches!(arg.get_action(), ArgAction::Version)
                && arg.is_global_set()
        });
        if command.is_propagate_version_set() && !version_replaced {
            return Err(SyntaxError::PropagatedVersionWithSubcommands(
                command.get_name().to_owned(),
            ));
        }
        // Clap also reports a missing version as disabled. A probe distinguishes
        // that default from an explicit setting inherited by child commands.
        let version_disabled = command
            .clone()
            .version("probe")
            .is_disable_version_flag_set();
        if command.is_disable_help_flag_set()
            || (version_disabled && !version_replaced)
            || command.is_disable_help_subcommand_set()
        {
            return Err(SyntaxError::UnsupportedBuiltinInheritance(
                command.get_name().to_owned(),
            ));
        }
    }
    if command.get_subcommands().next().is_some()
        && local_args.iter().any(|arg| arg.is_positional())
    {
        return Err(SyntaxError::AmbiguousPositionals(
            command.get_name().to_owned(),
        ));
    }

    let mut long_names: Vec<(String, &Arg)> = Vec::new();
    let mut short_names: Vec<(char, &Arg)> = Vec::new();
    for arg in inherited_globals
        .iter()
        .copied()
        .chain(local_args.iter().copied())
    {
        if arg.is_positional() {
            continue;
        }
        check_arity(arg)?;
        if let Some(long) = arg.get_long() {
            long_names.push((long.to_owned(), arg));
        }
        long_names.extend(
            arg.get_all_aliases()
                .unwrap_or_default()
                .into_iter()
                .map(|alias| (alias.to_owned(), arg)),
        );
        if let Some(short) = arg.get_short() {
            short_names.push((short, arg));
        }
        short_names.extend(
            arg.get_all_short_aliases()
                .unwrap_or_default()
                .into_iter()
                .map(|alias| (alias, arg)),
        );
    }
    check_long_names(&long_names, command.get_name())?;
    check_short_names(&short_names, command.get_name())?;
    if long_names.iter().any(|(name, _)| {
        (!command.is_disable_help_flag_set() && name.eq_ignore_ascii_case("help"))
            || (command.get_version().is_some()
                && !command.is_disable_version_flag_set()
                && name.eq_ignore_ascii_case("version"))
    }) {
        return Err(SyntaxError::CaseFoldCollision(
            command.get_name().to_owned(),
        ));
    }
    if short_names.iter().any(|(name, _)| {
        (!command.is_disable_help_flag_set() && name.eq_ignore_ascii_case(&'h'))
            || (command.get_version().is_some()
                && !command.is_disable_version_flag_set()
                && name.eq_ignore_ascii_case(&'V'))
    }) {
        return Err(SyntaxError::CaseFoldCollision(
            command.get_name().to_owned(),
        ));
    }

    let mut child_globals = inherited_globals.to_vec();
    child_globals.extend(local_args.iter().copied().filter(|arg| arg.is_global_set()));
    for subcommand in command.get_subcommands() {
        check_subcommand_names(command, subcommand)?;
        if !command.is_disable_help_subcommand_set()
            && iter::once(subcommand.get_name())
                .chain(subcommand.get_all_aliases())
                .any(|name| name.eq_ignore_ascii_case("help"))
        {
            return Err(SyntaxError::CaseFoldCollision(
                command.get_name().to_owned(),
            ));
        }
        validate_tree(subcommand, &child_globals)?;
    }
    Ok(())
}

fn check_long_names(names: &[(String, &Arg)], context: &str) -> Result<(), SyntaxError> {
    for (index, (name, arg)) in names.iter().enumerate() {
        if names.iter().take(index).any(|(other_name, other_arg)| {
            name.eq_ignore_ascii_case(other_name) && !ptr::eq(*arg, *other_arg)
        }) {
            return Err(SyntaxError::CaseFoldCollision(context.to_owned()));
        }
    }
    Ok(())
}

fn check_short_names(names: &[(char, &Arg)], context: &str) -> Result<(), SyntaxError> {
    for (index, (name, arg)) in names.iter().enumerate() {
        if names.iter().take(index).any(|(other_name, other_arg)| {
            name.eq_ignore_ascii_case(other_name) && !ptr::eq(*arg, *other_arg)
        }) {
            return Err(SyntaxError::CaseFoldCollision(context.to_owned()));
        }
    }
    Ok(())
}

fn check_subcommand_names(parent: &Command, child: &Command) -> Result<(), SyntaxError> {
    let child_names = iter::once(child.get_name()).chain(child.get_all_aliases());
    for name in child_names {
        for other in parent.get_subcommands() {
            if ptr::eq(child, other) {
                continue;
            }
            if other.get_name().eq_ignore_ascii_case(name)
                || other
                    .get_all_aliases()
                    .any(|alias| alias.eq_ignore_ascii_case(name))
            {
                return Err(SyntaxError::CaseFoldCollision(parent.get_name().to_owned()));
            }
        }
    }
    Ok(())
}

#![allow(clippy::panic_in_result_fn)]

use super::*;

#[test]
fn folds_known_syntax_but_preserves_values_and_delimiter_tail() -> Result<(), SyntaxError> {
    let command = Command::new("tool").arg(Arg::new("file").long("file").short('f'));
    let args = [
        "--FILE=HTTPS://Example.COM/a?Q=MiXeD",
        "-F",
        "./SomePath",
        "--",
        "--FILE",
    ]
    .into_iter()
    .map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(
        got,
        [
            "--file=HTTPS://Example.COM/a?Q=MiXeD",
            "-f",
            "./SomePath",
            "--",
            "--FILE"
        ]
        .map(OsString::from)
    );
    Ok(())
}

#[test]
fn folds_nested_commands_and_builtin_flags() -> Result<(), SyntaxError> {
    let command = Command::new("tool")
        .subcommand(Command::new("fetch").arg(Arg::new("output").short('o').long("output")));
    let args = ["FeTcH", "--HeLp"].into_iter().map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(got, ["fetch", "--help"].map(OsString::from));
    Ok(())
}

#[test]
fn folds_claps_generated_help_subcommand_path() -> Result<(), SyntaxError> {
    let command = Command::new("tool").subcommand(Command::new("fetch"));
    let args = ["HeLp", "FeTcH"].into_iter().map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(got, ["help", "fetch"].map(OsString::from));
    Ok(())
}

#[test]
fn disabled_generated_help_with_children_fails_closed() {
    let command = Command::new("tool")
        .disable_help_subcommand(true)
        .subcommand(Command::new("fetch"));
    assert!(matches!(
        normalize_args(&command, [OsString::from("HeLp")]),
        Err(SyntaxError::UnsupportedBuiltinInheritance(_))
    ));
}

#[test]
fn disabled_builtin_flags_can_be_used_by_custom_options() -> Result<(), SyntaxError> {
    let command = Command::new("tool")
        .version("1.0")
        .disable_help_flag(true)
        .disable_version_flag(true)
        .arg(
            Arg::new("home")
                .long("help")
                .short('h')
                .action(ArgAction::SetTrue),
        )
        .arg(
            Arg::new("verbose")
                .long("version")
                .short('v')
                .action(ArgAction::SetTrue),
        );
    let args = ["--HELP", "-H", "--VERSION", "-V"]
        .into_iter()
        .map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(got, ["--help", "-h", "--version", "-v"].map(OsString::from));
    Ok(())
}

#[test]
fn folds_long_and_short_aliases_to_primary_spellings() -> Result<(), SyntaxError> {
    let command = Command::new("tool").arg(
        Arg::new("destination")
            .long("destination")
            .alias("dest")
            .short('d')
            .short_alias('x')
            .action(ArgAction::SetTrue),
    );
    let args = ["--DEST", "-X"].into_iter().map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(got, ["--destination", "-d"].map(OsString::from));
    Ok(())
}

#[test]
fn handles_short_clusters_attached_values_and_flag_looking_values() -> Result<(), SyntaxError> {
    let command = Command::new("tool")
        .arg(Arg::new("force").short('f').action(ArgAction::SetTrue))
        .arg(Arg::new("output").short('o').long("output"));
    let args = ["-FOresult", "--OUTPUT", "--not-a-known-option"]
        .into_iter()
        .map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(
        got,
        ["-foresult", "--output", "--not-a-known-option"].map(OsString::from)
    );
    Ok(())
}

#[test]
fn delimiter_after_an_option_preserves_every_following_value() -> Result<(), SyntaxError> {
    let command = Command::new("tool").arg(Arg::new("output").long("output"));
    let args = ["--OUTPUT", "--", "--HELP", "MiXeD"]
        .into_iter()
        .map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(
        got,
        ["--output", "--", "--HELP", "MiXeD"].map(OsString::from)
    );
    Ok(())
}

#[test]
fn global_options_are_normalized_after_nested_subcommand() -> Result<(), SyntaxError> {
    let command = Command::new("tool")
        .arg(Arg::new("config").long("config").global(true))
        .subcommand(Command::new("fetch"));
    let args = ["FETCH", "--CONFIG", "settings.toml"]
        .into_iter()
        .map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(
        got,
        ["fetch", "--config", "settings.toml"].map(OsString::from)
    );
    Ok(())
}

#[test]
fn rejects_case_collisions_before_parsing_any_input() {
    let command = Command::new("tool")
        .arg(Arg::new("first").long("file"))
        .arg(Arg::new("second").long("FILE"));
    assert!(matches!(
        normalize_args(&command, []),
        Err(SyntaxError::CaseFoldCollision(_))
    ));

    let commands = Command::new("tool")
        .subcommand(Command::new("fetch"))
        .subcommand(Command::new("FETCH"));
    assert!(matches!(
        normalize_args(&commands, []),
        Err(SyntaxError::CaseFoldCollision(_))
    ));
}

#[test]
fn rejects_explicit_help_subcommand_name_or_alias() {
    let named_help = Command::new("tool").subcommand(Command::new("HELP"));
    assert!(matches!(
        normalize_args(&named_help, []),
        Err(SyntaxError::CaseFoldCollision(_))
    ));

    let aliased_help = Command::new("tool").subcommand(Command::new("manual").alias("help"));
    assert!(matches!(
        normalize_args(&aliased_help, []),
        Err(SyntaxError::CaseFoldCollision(_))
    ));
}

#[test]
fn rejects_raw_parent_builtin_settings_with_subcommands() {
    let propagated = Command::new("tool")
        .propagate_version(true)
        .subcommand(Command::new("fetch"));
    assert!(matches!(
        normalize_args(&propagated, []),
        Err(SyntaxError::PropagatedVersionWithSubcommands(_))
    ));

    let no_help_flag = Command::new("tool")
        .disable_help_flag(true)
        .subcommand(Command::new("fetch"));
    assert!(matches!(
        normalize_args(&no_help_flag, []),
        Err(SyntaxError::UnsupportedBuiltinInheritance(_))
    ));

    let no_version_flag = Command::new("tool")
        .version("1.0")
        .disable_version_flag(true)
        .subcommand(Command::new("fetch"));
    assert!(matches!(
        normalize_args(&no_version_flag, []),
        Err(SyntaxError::UnsupportedBuiltinInheritance(_))
    ));

    let versionless_parent_disabled = Command::new("tool")
        .disable_version_flag(true)
        .subcommand(Command::new("fetch").version("1.0"));
    assert!(matches!(
        normalize_args(&versionless_parent_disabled, []),
        Err(SyntaxError::UnsupportedBuiltinInheritance(_))
    ));

    let no_help_subcommand = Command::new("tool")
        .disable_help_subcommand(true)
        .subcommand(Command::new("fetch"));
    assert!(matches!(
        normalize_args(&no_help_subcommand, []),
        Err(SyntaxError::UnsupportedBuiltinInheritance(_))
    ));
}

#[test]
fn nested_commands_without_versions_still_normalize() -> Result<(), SyntaxError> {
    let command =
        Command::new("tool").subcommand(Command::new("policy").subcommand(Command::new("show")));
    let args = ["POLICY", "SHOW"].into_iter().map(OsString::from);
    let got = normalize_args(&command, args)?;
    assert_eq!(got, ["policy", "show"].map(OsString::from));
    Ok(())
}

#[test]
fn rejects_grammar_that_cannot_preserve_values_unambiguously() {
    let multiple = Command::new("tool").arg(Arg::new("files").long("files").num_args(1..));
    assert!(matches!(
        normalize_args(&multiple, []),
        Err(SyntaxError::UnsupportedArity(_))
    ));

    let ambiguous = Command::new("tool")
        .arg(Arg::new("value"))
        .subcommand(Command::new("fetch"));
    assert!(matches!(
        normalize_args(&ambiguous, []),
        Err(SyntaxError::AmbiguousPositionals(_))
    ));
}

#[test]
fn non_utf8_argument_is_preserved() -> Result<(), SyntaxError> {
    #[cfg(unix)]
    {
        use std::os::unix::ffi::{OsStrExt, OsStringExt};
        let bytes = vec![b'/', 0xff];
        let arg = OsString::from_vec(bytes.clone());
        let got = normalize_args(&Command::new("tool"), [arg])?;
        assert_eq!(
            got.first().map(|value| value.as_os_str().as_bytes()),
            Some(bytes.as_slice())
        );
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn rejects_non_utf8_attached_option_values_but_keeps_plain_values() -> Result<(), SyntaxError> {
    use std::os::unix::ffi::OsStringExt;

    let command = Command::new("tool").arg(Arg::new("output").long("output").short('o'));
    let plain_value = OsString::from_vec(vec![b'/', 0xff]);
    let normalized = normalize_args(&command, [plain_value.clone()])?;
    assert_eq!(normalized, [plain_value]);

    let after_delimiter = OsString::from_vec(vec![
        b'-', b'-', b'O', b'U', b'T', b'P', b'U', b'T', b'=', 0xff,
    ]);
    let normalized = normalize_args(&command, [OsString::from("--"), after_delimiter.clone()])?;
    assert_eq!(normalized, [OsString::from("--"), after_delimiter]);

    let attached_value = OsString::from_vec(vec![
        b'-', b'-', b'O', b'U', b'T', b'P', b'U', b'T', b'=', b'/', b't', b'm', b'p', b'/', 0xff,
    ]);
    assert!(matches!(
        normalize_args(&command, [attached_value]),
        Err(SyntaxError::NonUtf8OptionToken)
    ));

    let separated = OsString::from_vec(vec![b'/', b't', b'm', b'p', b'/', 0xff]);
    let normalized = normalize_args(&command, [OsString::from("-O"), separated.clone()])?;
    assert_eq!(normalized, [OsString::from("-o"), separated]);

    let short_attached = OsString::from_vec(vec![b'-', b'O', b'/', b't', b'm', b'p', b'/', 0xff]);
    assert!(matches!(
        normalize_args(&command, [short_attached]),
        Err(SyntaxError::NonUtf8OptionToken)
    ));
    Ok(())
}

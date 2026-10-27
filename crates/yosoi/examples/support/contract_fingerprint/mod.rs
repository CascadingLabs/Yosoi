//! Private spike modules, not a proposed stable SDK API.
use std::result as std_result;
use std::{error::Error, io};
type Result<T = ()> = std_result::Result<T, Box<dyn Error + Send + Sync>>;
fn error(message: &str) -> Box<dyn Error + Send + Sync> {
    io::Error::other(message).into()
}
fn fail<T>(message: &str) -> Result<T> {
    Err(error(message))
}
mod fingerprint;
mod recipe;
mod runner;
mod storage;
mod structure;
pub use runner::{evaluate, freeze, replay, sensitivity};
mod controls;

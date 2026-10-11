//! Owned provider facts staged for later artifact admission. This module does not finalize captures.
mod facts;
mod result;
mod staging;
mod terminal;

pub use facts::*;
pub use result::*;
pub use staging::*;
pub use terminal::*;

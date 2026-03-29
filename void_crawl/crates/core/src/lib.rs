//! `void_crawl_core` — a clean async CDP wrapper built on chromiumoxide.
//!
//! This crate provides `BrowserSession` and `Page` as the primary API.

pub mod error;
pub mod page;
pub mod pool;
pub mod session;
pub mod stealth;

pub use error::{Result, YosoiError};
pub use page::Page;
pub use pool::{BrowserPool, PoolConfig, PooledTab};
pub use session::{BrowserMode, BrowserSession, BrowserSessionBuilder};
pub use stealth::StealthConfig;

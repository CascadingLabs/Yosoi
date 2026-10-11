use std::{io::Read, str};

use flate2::read::GzDecoder;
use roxmltree::Node;

use super::ParseError;

/// The parsed contents of either a sitemap URL set or a sitemap index.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Sitemap {
    pub kind: SitemapKind,
    pub locations: Vec<String>,
    pub truncated: bool,
    /// Number of decoded XML bytes supplied to the XML parser.
    pub decoded_bytes: usize,
}

/// Identifies whether sitemap locations point to pages or nested sitemap files.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SitemapKind {
    Urls,
    Index,
}

/// Parses XML sitemap data, transparently decompressing gzip input.
///
/// max_bytes limits the uncompressed XML size and max_entries limits the
/// retained locations. Entries beyond the retention limit are still validated.
pub fn parse_sitemap(
    bytes: &[u8],
    max_entries: usize,
    max_bytes: usize,
) -> Result<Sitemap, ParseError> {
    let xml_bytes = if bytes.starts_with(&[0x1f, 0x8b]) {
        read_bounded_gzip(bytes, max_bytes)?
    } else {
        if bytes.len() > max_bytes {
            return Err(ParseError::ByteLimitExceeded { limit: max_bytes });
        }
        bytes.to_vec()
    };
    let xml = str::from_utf8(&xml_bytes).map_err(|_| ParseError::InvalidSitemapEntry {
        entry: "XML document",
        reason: "document is not UTF-8",
    })?;

    let document = roxmltree::Document::parse(xml)?;
    let root = document.root_element();
    let (kind, entry_name) = match root.tag_name().name() {
        "urlset" => (SitemapKind::Urls, "url"),
        "sitemapindex" => (SitemapKind::Index, "sitemap"),
        root_name => {
            return Err(ParseError::UnsupportedSitemapRoot {
                root: root_name.to_owned(),
            });
        }
    };

    let mut locations = Vec::with_capacity(max_entries.min(256));
    let mut truncated = false;
    for entry in root
        .children()
        .filter(|node| node.is_element() && node.tag_name().name() == entry_name)
    {
        // Validate every supported entry, including ones omitted after the cap.
        let location = sitemap_location(entry, entry_name)?;
        if locations.len() < max_entries {
            locations.push(location);
        } else {
            truncated = true;
        }
    }

    Ok(Sitemap {
        kind,
        locations,
        truncated,
        decoded_bytes: xml_bytes.len(),
    })
}

fn sitemap_location(
    entry: roxmltree::Node<'_, '_>,
    entry_name: &'static str,
) -> Result<String, ParseError> {
    let mut locations = entry
        .children()
        .filter(|node| node.is_element() && node.tag_name().name() == "loc");
    let Some(location_node) = locations.next() else {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "entry has no direct loc child",
        });
    };
    if locations.next().is_some() {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "entry has multiple direct loc children",
        });
    }

    if location_node.children().any(|node| node.is_element()) {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "loc contains nested elements",
        });
    }
    let mut value = String::new();
    for child in location_node.children().filter(Node::is_text) {
        if let Some(text) = child.text() {
            value.push_str(text);
        }
    }
    let value = value.trim();
    if value.is_empty() {
        return Err(ParseError::InvalidSitemapEntry {
            entry: entry_name,
            reason: "loc is empty",
        });
    }
    Ok(value.to_owned())
}

fn read_bounded_gzip(bytes: &[u8], max_bytes: usize) -> Result<Vec<u8>, ParseError> {
    let limit = u64::try_from(max_bytes)
        .unwrap_or(u64::MAX)
        .saturating_add(1);
    let decoder = GzDecoder::new(bytes);
    let mut bounded = decoder.take(limit);
    let mut decoded = Vec::new();
    bounded
        .read_to_end(&mut decoded)
        .map_err(ParseError::InvalidGzip)?;
    if decoded.len() > max_bytes {
        return Err(ParseError::ByteLimitExceeded { limit: max_bytes });
    }
    Ok(decoded)
}

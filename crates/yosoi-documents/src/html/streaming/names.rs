#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub(super) struct NameKey {
    low: u64,
    high: u64,
}

impl NameKey {
    pub(super) fn from_lower(bytes: &[u8]) -> Option<Self> {
        Self::pack(bytes, false)
    }

    pub(super) fn from_ascii_casefold(bytes: &[u8]) -> Option<Self> {
        Self::pack(bytes, true)
    }

    fn pack(bytes: &[u8], fold_uppercase: bool) -> Option<Self> {
        if bytes.is_empty() || bytes.len() > 16 {
            return None;
        }
        let mut low = [0_u8; 8];
        let mut high = [0_u8; 8];
        for (slot, byte) in low.iter_mut().chain(&mut high).zip(bytes.iter().copied()) {
            if !byte.is_ascii() || (!fold_uppercase && byte.is_ascii_uppercase()) {
                return None;
            }
            *slot = if fold_uppercase {
                byte.to_ascii_lowercase()
            } else {
                byte
            };
        }
        Some(Self {
            low: u64::from_le_bytes(low),
            high: u64::from_le_bytes(high),
        })
    }

    #[allow(
        clippy::arithmetic_side_effects,
        clippy::as_conversions,
        clippy::indexing_slicing,
        reason = "const loop proves index is below the validated sixteen-byte literal length; Rust 1.99 lacks const slice::get"
    )]
    const fn literal(bytes: &[u8]) -> Self {
        let mut result = Self { low: 0, high: 0 };
        let mut index = 0_usize;
        while index < bytes.len() {
            let lane = (index % 8) * 8;
            let shifted = (bytes[index] as u64) << lane;
            if index < 8 {
                result.low |= shifted;
            } else {
                result.high |= shifted;
            }
            index += 1;
        }
        result
    }
}

pub(super) const HTML: NameKey = NameKey::literal(b"html");
pub(super) const HEAD: NameKey = NameKey::literal(b"head");
pub(super) const BODY: NameKey = NameKey::literal(b"body");
pub(super) const ID: NameKey = NameKey::literal(b"id");
pub(super) const CLASS: NameKey = NameKey::literal(b"class");
pub(super) const P: NameKey = NameKey::literal(b"p");
pub(super) const LI: NameKey = NameKey::literal(b"li");
pub(super) const DT: NameKey = NameKey::literal(b"dt");
pub(super) const DD: NameKey = NameKey::literal(b"dd");
pub(super) const BUTTON: NameKey = NameKey::literal(b"button");
pub(super) const FORM: NameKey = NameKey::literal(b"form");
pub(super) const TABLE: NameKey = NameKey::literal(b"table");
pub(super) const TBODY: NameKey = NameKey::literal(b"tbody");
pub(super) const COLGROUP: NameKey = NameKey::literal(b"colgroup");
pub(super) const SVG: NameKey = NameKey::literal(b"svg");
pub(super) const MATH: NameKey = NameKey::literal(b"math");
pub(super) const BR: NameKey = NameKey::literal(b"br");
pub(super) const AREA: NameKey = NameKey::literal(b"area");
pub(super) const BASE: NameKey = NameKey::literal(b"base");
pub(super) const COL: NameKey = NameKey::literal(b"col");
pub(super) const EMBED: NameKey = NameKey::literal(b"embed");
pub(super) const HR: NameKey = NameKey::literal(b"hr");
pub(super) const IMG: NameKey = NameKey::literal(b"img");
pub(super) const INPUT: NameKey = NameKey::literal(b"input");
pub(super) const LINK: NameKey = NameKey::literal(b"link");
pub(super) const META: NameKey = NameKey::literal(b"meta");
pub(super) const PARAM: NameKey = NameKey::literal(b"param");
pub(super) const SOURCE: NameKey = NameKey::literal(b"source");
pub(super) const TRACK: NameKey = NameKey::literal(b"track");
pub(super) const WBR: NameKey = NameKey::literal(b"wbr");
pub(super) const H1: NameKey = NameKey::literal(b"h1");
pub(super) const H2: NameKey = NameKey::literal(b"h2");
pub(super) const H3: NameKey = NameKey::literal(b"h3");
pub(super) const H4: NameKey = NameKey::literal(b"h4");
pub(super) const H5: NameKey = NameKey::literal(b"h5");
pub(super) const H6: NameKey = NameKey::literal(b"h6");
pub(super) const FRAMESET: NameKey = NameKey::literal(b"frameset");
pub(super) const IFRAME: NameKey = NameKey::literal(b"iframe");
pub(super) const NOEMBED: NameKey = NameKey::literal(b"noembed");
pub(super) const NOFRAMES: NameKey = NameKey::literal(b"noframes");
pub(super) const NOSCRIPT: NameKey = NameKey::literal(b"noscript");
pub(super) const PLAINTEXT: NameKey = NameKey::literal(b"plaintext");
pub(super) const SCRIPT: NameKey = NameKey::literal(b"script");
pub(super) const SELECT: NameKey = NameKey::literal(b"select");
pub(super) const SELECTEDCONTENT: NameKey = NameKey::literal(b"selectedcontent");
pub(super) const STYLE: NameKey = NameKey::literal(b"style");
pub(super) const TEMPLATE: NameKey = NameKey::literal(b"template");
pub(super) const TEXTAREA: NameKey = NameKey::literal(b"textarea");
pub(super) const TITLE: NameKey = NameKey::literal(b"title");
pub(super) const XMP: NameKey = NameKey::literal(b"xmp");
pub(super) const A: NameKey = NameKey::literal(b"a");
pub(super) const B: NameKey = NameKey::literal(b"b");
pub(super) const BIG: NameKey = NameKey::literal(b"big");
pub(super) const CODE: NameKey = NameKey::literal(b"code");
pub(super) const EM: NameKey = NameKey::literal(b"em");
pub(super) const FONT: NameKey = NameKey::literal(b"font");
pub(super) const I: NameKey = NameKey::literal(b"i");
pub(super) const NOBR: NameKey = NameKey::literal(b"nobr");
pub(super) const S: NameKey = NameKey::literal(b"s");
pub(super) const SMALL: NameKey = NameKey::literal(b"small");
pub(super) const STRIKE: NameKey = NameKey::literal(b"strike");
pub(super) const STRONG: NameKey = NameKey::literal(b"strong");
pub(super) const TT: NameKey = NameKey::literal(b"tt");
pub(super) const U: NameKey = NameKey::literal(b"u");
pub(super) const ADDRESS: NameKey = NameKey::literal(b"address");
pub(super) const ARTICLE: NameKey = NameKey::literal(b"article");
pub(super) const ASIDE: NameKey = NameKey::literal(b"aside");
pub(super) const BLOCKQUOTE: NameKey = NameKey::literal(b"blockquote");
pub(super) const DIV: NameKey = NameKey::literal(b"div");
pub(super) const DL: NameKey = NameKey::literal(b"dl");
pub(super) const FIELDSET: NameKey = NameKey::literal(b"fieldset");
pub(super) const FOOTER: NameKey = NameKey::literal(b"footer");
pub(super) const HEADER: NameKey = NameKey::literal(b"header");
pub(super) const HGROUP: NameKey = NameKey::literal(b"hgroup");
pub(super) const MAIN: NameKey = NameKey::literal(b"main");
pub(super) const MENU: NameKey = NameKey::literal(b"menu");
pub(super) const NAV: NameKey = NameKey::literal(b"nav");
pub(super) const OL: NameKey = NameKey::literal(b"ol");
pub(super) const PRE: NameKey = NameKey::literal(b"pre");
pub(super) const SECTION: NameKey = NameKey::literal(b"section");
pub(super) const UL: NameKey = NameKey::literal(b"ul");
pub(super) const CENTER: NameKey = NameKey::literal(b"center");
pub(super) const DETAILS: NameKey = NameKey::literal(b"details");
pub(super) const DIALOG: NameKey = NameKey::literal(b"dialog");
pub(super) const DIR: NameKey = NameKey::literal(b"dir");
pub(super) const FIGCAPTION: NameKey = NameKey::literal(b"figcaption");
pub(super) const FIGURE: NameKey = NameKey::literal(b"figure");
pub(super) const KEYGEN: NameKey = NameKey::literal(b"keygen");
pub(super) const LISTING: NameKey = NameKey::literal(b"listing");
pub(super) const SEARCH: NameKey = NameKey::literal(b"search");
pub(super) const SUMMARY: NameKey = NameKey::literal(b"summary");
pub(super) const MARK: NameKey = NameKey::literal(b"mark");
pub(super) const SPAN: NameKey = NameKey::literal(b"span");
pub(super) const TR: NameKey = NameKey::literal(b"tr");
pub(super) const TD: NameKey = NameKey::literal(b"td");
pub(super) const PATH: NameKey = NameKey::literal(b"path");

use super::names::{
    A, ADDRESS, AREA, ARTICLE, ASIDE, B, BASE, BIG, BLOCKQUOTE, BODY, BR, BUTTON, CENTER, CODE,
    COL, DD, DETAILS, DIALOG, DIR, DIV, DL, DT, EM, EMBED, FIELDSET, FIGCAPTION, FIGURE, FONT,
    FOOTER, FORM, FRAMESET, H1, H2, H3, H4, H5, H6, HEAD, HEADER, HGROUP, HR, HTML, I, IFRAME, IMG,
    INPUT, KEYGEN, LI, LINK, LISTING, MAIN, MARK, MATH, MENU, META, NAV, NOBR, NOEMBED, NOFRAMES,
    NOSCRIPT, NameKey, OL, P, PARAM, PLAINTEXT, PRE, S, SCRIPT, SEARCH, SECTION, SELECT,
    SELECTEDCONTENT, SMALL, SOURCE, SPAN, STRIKE, STRONG, STYLE, SUMMARY, SVG, TABLE, TEMPLATE,
    TEXTAREA, TITLE, TRACK, TT, U, UL, WBR, XMP,
};
use super::plan::CompiledSelectorPlan;
use super::scanner::{ImpliedKind, OpenElement, TagFacts};

pub(super) fn classify_tag(
    name: NameKey,
    plan: &CompiledSelectorPlan,
    inside_foreign: bool,
) -> TagFacts {
    let implied = match name {
        P => ImpliedKind::Paragraph,
        LI => ImpliedKind::ListItem,
        DT => ImpliedKind::DefinitionTerm,
        DD => ImpliedKind::DefinitionDescription,
        H1 | H2 | H3 | H4 | H5 | H6 => ImpliedKind::Heading,
        BUTTON => ImpliedKind::Button,
        FORM => ImpliedKind::Form,
        _ => ImpliedKind::Other,
    };
    TagFacts {
        leftmost: plan.leftmost.tag == name,
        rightmost: plan.rightmost.tag == name,
        void: is_void_html_tag(name),
        unsupported: is_unsupported_tag(name),
        formatting: is_formatting_tag(name),
        table: name == TABLE,
        foreign: inside_foreign || matches!(name, SVG | MATH),
        implied,
        closes_paragraph: closes_paragraph(name),
    }
}

pub(super) fn implied_close_position(
    stack: &[OpenElement],
    new_kind: ImpliedKind,
    closes_paragraph: bool,
) -> Option<usize> {
    stack.iter().rposition(|element| {
        (element.implied == ImpliedKind::ListItem && new_kind == ImpliedKind::ListItem)
            || (matches!(
                element.implied,
                ImpliedKind::DefinitionTerm | ImpliedKind::DefinitionDescription
            ) && matches!(
                new_kind,
                ImpliedKind::DefinitionTerm | ImpliedKind::DefinitionDescription
            ))
            || (element.implied == ImpliedKind::Heading && new_kind == ImpliedKind::Heading)
            || (element.implied == ImpliedKind::Button && new_kind == ImpliedKind::Button)
            || (element.implied == ImpliedKind::Form && new_kind == ImpliedKind::Form)
            || (element.implied == ImpliedKind::Paragraph
                && element.closes_paragraph
                && closes_paragraph)
    })
}

pub(super) const fn could_close_outer_record(
    outer: ImpliedKind,
    inner: ImpliedKind,
    closes_paragraph: bool,
) -> bool {
    match outer {
        ImpliedKind::Other => false,
        ImpliedKind::Paragraph => closes_paragraph,
        ImpliedKind::ListItem => matches!(inner, ImpliedKind::ListItem),
        ImpliedKind::DefinitionTerm | ImpliedKind::DefinitionDescription => matches!(
            inner,
            ImpliedKind::DefinitionTerm | ImpliedKind::DefinitionDescription
        ),
        ImpliedKind::Heading => matches!(inner, ImpliedKind::Heading),
        ImpliedKind::Button => matches!(inner, ImpliedKind::Button),
        ImpliedKind::Form => matches!(inner, ImpliedKind::Form),
    }
}

#[allow(
    clippy::missing_const_for_fn,
    reason = "Rust 1.98 cannot evaluate str pattern matches in const functions"
)]
pub(super) fn closes_paragraph(tag: NameKey) -> bool {
    matches!(
        tag,
        ADDRESS
            | ARTICLE
            | ASIDE
            | BLOCKQUOTE
            | CENTER
            | DETAILS
            | DIALOG
            | DIR
            | DD
            | DIV
            | DL
            | DT
            | FIELDSET
            | FIGCAPTION
            | FIGURE
            | FOOTER
            | FORM
            | H1
            | H2
            | H3
            | H4
            | H5
            | H6
            | HEADER
            | HGROUP
            | HR
            | KEYGEN
            | LI
            | LISTING
            | MAIN
            | MENU
            | NAV
            | OL
            | P
            | PRE
            | SEARCH
            | SECTION
            | SUMMARY
            | TABLE
            | UL
    )
}

pub(super) const fn is_void_html_tag(tag: NameKey) -> bool {
    matches!(
        tag,
        AREA | BASE
            | BR
            | COL
            | EMBED
            | HR
            | IMG
            | INPUT
            | KEYGEN
            | LINK
            | META
            | PARAM
            | SOURCE
            | TRACK
            | WBR
    )
}
#[allow(
    clippy::missing_const_for_fn,
    reason = "Rust 1.98 cannot evaluate str pattern matches in const functions"
)]
pub(super) fn is_unsupported_tag(tag: NameKey) -> bool {
    matches!(
        tag,
        FRAMESET
            | FORM
            | IFRAME
            | NOEMBED
            | NOFRAMES
            | NOSCRIPT
            | PLAINTEXT
            | SCRIPT
            | SELECT
            | SELECTEDCONTENT
            | STYLE
            | TEMPLATE
            | TEXTAREA
            | TITLE
            | XMP
    )
}
#[allow(
    clippy::missing_const_for_fn,
    reason = "Rust 1.98 cannot evaluate str pattern matches in const functions"
)]
pub(super) fn is_formatting_tag(tag: NameKey) -> bool {
    matches!(
        tag,
        A | B | BIG | CODE | EM | FONT | I | NOBR | S | SMALL | STRIKE | STRONG | TT | U
    )
}

pub(super) const fn is_heading(tag: NameKey) -> bool {
    matches!(tag, H1 | H2 | H3 | H4 | H5 | H6)
}

pub(super) const fn is_certified_tree_text_tag(tag: NameKey) -> bool {
    matches!(
        tag,
        HTML | HEAD
            | BODY
            | ADDRESS
            | ARTICLE
            | ASIDE
            | BLOCKQUOTE
            | CENTER
            | DETAILS
            | DIALOG
            | DIR
            | DIV
            | DL
            | DT
            | DD
            | FIELDSET
            | FIGCAPTION
            | FIGURE
            | FOOTER
            | H1
            | H2
            | H3
            | H4
            | H5
            | H6
            | HEADER
            | HGROUP
            | HR
            | LI
            | MAIN
            | MARK
            | MENU
            | NAV
            | OL
            | P
            | PRE
            | SEARCH
            | SECTION
            | SPAN
            | SUMMARY
            | UL
            | BR
            | IMG
            | INPUT
            | WBR
    )
}

pub(super) fn is_slow_record_name(name: &[u8]) -> bool {
    match name.first().copied() {
        Some(b'a') => name == b"a",
        Some(b'b') => matches!(name, b"b" | b"big" | b"button"),
        Some(b'c') => name == b"code",
        Some(b'd') => matches!(name, b"dd" | b"dt"),
        Some(b'e') => name == b"em",
        Some(b'f') => matches!(name, b"font" | b"form" | b"frameset"),
        Some(b'i') => matches!(name, b"i" | b"iframe"),
        Some(b'm') => name == b"math",
        Some(b'n') => matches!(name, b"nobr" | b"noembed" | b"noscript"),
        Some(b'p') => name == b"plaintext",
        Some(b's') => matches!(
            name,
            b"s" | b"script"
                | b"select"
                | b"selectedcontent"
                | b"small"
                | b"strike"
                | b"strong"
                | b"style"
                | b"svg"
        ),
        Some(b't') => matches!(name, b"template" | b"textarea" | b"tt"),
        Some(b'u') => name == b"u",
        Some(b'x') => name == b"xmp",
        _ => false,
    }
}

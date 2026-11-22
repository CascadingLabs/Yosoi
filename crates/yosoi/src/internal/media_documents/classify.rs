#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum MediaKind {
    Image,
    Video,
    Audio,
    Binary,
}

pub(super) fn detected_kind(bytes: &[u8]) -> MediaKind {
    match infer::get(bytes).map(|kind| kind.matcher_type()) {
        Some(infer::MatcherType::Image) => MediaKind::Image,
        Some(infer::MatcherType::Video) => MediaKind::Video,
        Some(infer::MatcherType::Audio) => MediaKind::Audio,
        Some(
            infer::MatcherType::App
            | infer::MatcherType::Archive
            | infer::MatcherType::Book
            | infer::MatcherType::Doc
            | infer::MatcherType::Font
            | infer::MatcherType::Text
            | infer::MatcherType::Custom,
        )
        | None => MediaKind::Binary,
    }
}

pub(super) const fn expected_type_name(kind: MediaKind) -> &'static str {
    match kind {
        MediaKind::Image => "image",
        MediaKind::Video => "video",
        MediaKind::Audio => "audio",
        MediaKind::Binary => "binary",
    }
}

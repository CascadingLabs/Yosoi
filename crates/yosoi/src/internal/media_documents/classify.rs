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

pub(super) fn accepts_probe_validated_video(container: &str, detected: MediaKind) -> bool {
    match container {
        // The pinned signature matcher reports generic Ogg pages as audio; this basis is
        // recorded only after FFprobe confirms a video stream in a self-contained Ogg file.
        "ogg" => detected == MediaKind::Audio,
        // MPEG-TS has no fixed leading signature for the media detector. Accept an
        // unrecognized or audio-classified prefix only after FFprobe confirms its video stream.
        "mpegts" => matches!(detected, MediaKind::Audio | MediaKind::Binary),
        _ => false,
    }
}

use super::*;

#[tokio::test]
async fn strict_decoders_distinguish_incomplete_boundary_from_invalid_input() {
    for prefix in [
        b"a\xc3".as_slice(),
        b"a\xe2",
        b"a\xe2\x98",
        b"a\xf0",
        b"a\xf0\x9f",
        b"a\xf0\x9f\x98",
    ] {
        decoding_case("Content-Type: text/plain;charset=utf-8\r\n", prefix, false).await;
    }
    decoding_case("Content-Type: text/plain;charset=utf-8\r\n", b"a\xff", true).await;
    for (header, incomplete, invalid) in [
        (
            "Content-Type: text/plain;charset=utf-16le\r\n",
            b"a\0x".as_slice(),
            b"a\0\0\xdc".as_slice(),
        ),
        (
            "Content-Type: text/plain;charset=utf-16le\r\n",
            b"a\0\0\xd8",
            b"a\0\0\xdc",
        ),
        (
            "Content-Type: text/plain;charset=utf-16be\r\n",
            b"\0ax",
            b"\0a\xdc\0",
        ),
        (
            "Content-Type: text/plain;charset=utf-16be\r\n",
            b"\0a\xd8\0",
            b"\0a\xdc\0",
        ),
        (
            "Content-Type: text/plain;charset=shift_jis\r\n",
            b"a\x82",
            b"a\x82\x20",
        ),
        (
            "Content-Type: text/plain;charset=gbk\r\n",
            b"a\x81",
            b"a\x81\x20",
        ),
    ] {
        decoding_case(header, incomplete, false).await;
        decoding_case(header, invalid, true).await;
    }
}

#[tokio::test]
async fn html_non_strict_replaces_invalid_but_marks_genuine_incomplete() {
    decoding_case(
        "Content-Type: text/html;charset=utf-8\r\n",
        b"<p>\xf0\x9f",
        false,
    )
    .await;
    let retained = b"<p>\xff";
    let mut full = retained.to_vec();
    full.extend_from_slice(b"TAIL");
    let (body, facts) = acquire(
        "Content-Type: text/html;charset=utf-8\r\n",
        &full,
        retained.len() as u64,
    )
    .await;
    let result = classify(&body, &facts, full.len());
    let view = decoded(result.decoding());
    assert_eq!(view.replacements(), 1);
    assert!(!view.incomplete_terminal_sequence());
    assert!(view.source_truncated());
    assert!(matches!(
        result.decoding(),
        CharacterDecodingOutcome::Complete(_)
    ));
}

#![allow(dead_code)]
//! Named immutable corpus. Digests are reviewed constants, never derived from capture output.
#[derive(Clone, Copy, Debug)]
pub struct CorpusCase {
    pub name: &'static str,
    pub status: u16,
    pub content_type: Option<&'static str>,
    pub bytes: &'static [u8],
    pub sha256: &'static str,
    pub format: &'static str,
    pub encoding: Option<&'static str>,
}
macro_rules! case {
    ($n:literal,$s:expr,$m:expr,$b:expr,$d:literal,$f:literal,$e:expr) => {
        CorpusCase {
            name: $n,
            status: $s,
            content_type: $m,
            bytes: $b,
            sha256: $d,
            format: $f,
            encoding: $e,
        }
    };
}
/// Independent representation expected after every successful coding vector.
pub const CODING_PLAIN: &[u8] = b"fixed coding fixture: snowman \xe2\x98\x83\n";
pub const CODING_PLAIN_SHA256: &str =
    "53c1c76996c350abbf1b743f4662c14d7cba4f694b0e88d82316d646f5ce3df6";
pub const CODING_GZIP: &[u8] = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03K\xcb\xacHMQH\xceO\xc9\xccKWH\xcb\xac()-J\xb5R(\xce\xcb/\xcfM\xccSx4\xa3\x99\x0b\x00\xe5\x17n\x8c\x22\x00\x00\x00";
pub const CODING_BR: &[u8] = b"!\x84\x00\x04fixed coding fixture: snowman \xe2\x98\x83\n\x03";
pub const CODING_ZLIB: &[u8] = b"x\x9cK\xcb\xacHMQH\xceO\xc9\xccKWH\xcb\xac()-J\xb5R(\xce\xcb/\xcfM\xccSx4\xa3\x99\x0b\x00\xe4\x91\rP";
/// Brotli representation wrapped in zlib: `Content-Encoding: br, deflate`.
pub const CODING_STACKED: &[u8] = b"x\x9cSla`I\xcb\xacHMQH\xceO\xc9\xccKW\x00rJJ\x8bR\xad\x14\x8a\xf3\xf2\xcbs\x13\xf3\x14\x1e\xcdh\xe6b\x06\x00\x0b&\r\xfc";

pub const CASES: &[CorpusCase] = &[
    case!(
        "static-html",
        200,
        Some("text/html; charset=utf-8"),
        b"<!doctype html><title>static</title>",
        "f610044a3067b31ed853a980a97f87636d123b62381504f60d017f49220e73f4",
        "html",
        Some("UTF-8")
    ),
    case!(
        "javascript-shell",
        200,
        Some("text/html"),
        b"<!doctype html><div id=\"app\"></div><script src=\"/app.js\"></script>",
        "6539e0332c99dd95067ab060e70365211a460cbadf943ac36165c60019381581",
        "html",
        Some("windows-1252")
    ),
    case!(
        "xml",
        200,
        Some("application/xml"),
        b"<?xml version=\"1.0\"?><feed/>",
        "9a47edf2a38da27d4e0cc68f2d2403e55e336e3966dc6a041dba10c30685b09e",
        "xml",
        Some("UTF-8")
    ),
    case!(
        "atom",
        200,
        Some("application/atom+xml"),
        b"<?xml version=\"1.0\"?><feed xmlns=\"http://www.w3.org/2005/Atom\"/>",
        "491e770c215c56f720d857dc7addd8df0432f2f84da0588fe19d7e71e6745d27",
        "xml",
        Some("UTF-8")
    ),
    case!(
        "xhtml",
        200,
        Some("application/xhtml+xml"),
        b"<?xml version=\"1.0\"?><html xmlns=\"http://www.w3.org/1999/xhtml\"/>",
        "ef34d137e428e8a1d3305ad37f23b764a5fbc52e23c2565dbfd9d007089faff1",
        "xhtml",
        Some("UTF-8")
    ),
    case!(
        "json",
        200,
        Some("application/json"),
        b"{\"ok\":true}",
        "4062edaf750fb8074e7e83e0c9028c94e32468a8b6f1614774328ef045150f93",
        "json",
        Some("UTF-8")
    ),
    case!(
        "problem-json",
        200,
        Some("application/problem+json"),
        b"{\"type\":\"fixture\"}",
        "2c3fa007e925205c6a4e28efc51ef48d9ae629217021dd1def01fa82eeaa3a7f",
        "json",
        Some("UTF-8")
    ),
    case!(
        "malformed-json",
        200,
        Some("application/json"),
        b"{\"broken\":",
        "cbdf3b1f91ae32fe1ea292ac6cccf19222f97929f531523f0d15d885052c00c4",
        "json",
        Some("UTF-8")
    ),
    case!(
        "plain-utf8",
        200,
        Some("text/plain; charset=utf-8"),
        "snowman: ☃".as_bytes(),
        "4c9461c161ad8ecae8057c4ca9f70e9eae57c14d2c2a346d2e4b1f5eff0b4350",
        "plain",
        Some("UTF-8")
    ),
    case!(
        "plain-windows-1252",
        200,
        Some("text/plain; charset=windows-1252"),
        b"price: \x809",
        "a38c42f062ea4053c785260f592c076271d1abd91263943fb6846548865fcb42",
        "plain",
        Some("windows-1252")
    ),
    case!(
        "empty-declared",
        200,
        Some("text/plain"),
        b"",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "plain",
        Some("UTF-8")
    ),
    case!(
        "empty-undeclared",
        200,
        None,
        b"",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "unknown",
        None
    ),
    case!(
        "html-404",
        404,
        Some("text/html"),
        b"<html><title>missing</title></html>",
        "1b80f0bf4d6004fa495b0bb7147844d2d7e51bf87eaca50d68552b5aef6e010e",
        "html",
        Some("windows-1252")
    ),
    case!(
        "malformed-json-500",
        500,
        Some("application/json"),
        b"{nope}",
        "926fce9f5b9d8dde66f34d6a52db47179d4fcfafe813e43724b51bfb9602e75f",
        "json",
        Some("UTF-8")
    ),
    case!(
        "binary",
        200,
        Some("application/octet-stream"),
        b"\0\x01\x02\xff",
        "3d1f57c984978ef98a18378c8166c1cb8ede02c03eeb6aee7e2f121dfeee3e56",
        "unknown",
        None
    ),
    case!(
        "csv",
        200,
        Some("text/csv"),
        b"a,b\n1,2\n",
        "492d5ea496056f1a6a6592241032fab764c321596317930b4fa0e1e8bc3b7470",
        "unsupported",
        None
    ),
    case!(
        "text-json",
        200,
        Some("text/json"),
        b"{\"alias\":1}",
        "b3c299b7f360819fbe02e819a9b4cf718dbd3513b97666977ddce2fc7e168ad1",
        "unsupported",
        None
    ),
    case!(
        "utf8-bom-conflict",
        200,
        Some("text/plain; charset=windows-1252"),
        b"\xef\xbb\xbfhello",
        "7489ebbcc2a00056ddaaaac190bce473e5c03696ea1bd8ed83cf59a174283862",
        "plain",
        Some("UTF-8")
    ),
    case!(
        "utf16le-bom",
        200,
        Some("text/plain; charset=utf-8"),
        b"\xff\xfeh\0i\0",
        "ef34ffe1058578c4df3c8c5c2e3db5d4c258c9334dc81b353a4f4d0d1f8e3bc9",
        "plain",
        Some("UTF-16LE")
    ),
    case!(
        "html-meta",
        200,
        Some("text/html"),
        b"<meta charset=windows-1252><p>\x80</p>",
        "be2189440b266e59a7d0ad9764832d4659c9ec78723ca855774bc775d47ce9a6",
        "html",
        Some("windows-1252")
    ),
    case!(
        "xml-declaration",
        200,
        Some("application/xml"),
        b"<?xml version=\"1.0\" encoding=\"windows-1252\"?><x>\x80</x>",
        "2d0e3e82135509bc4ab514d12c23331c48391b86274165f280c91823d32623fe",
        "xml",
        Some("windows-1252")
    ),
    case!(
        "json-bom",
        200,
        Some("application/json"),
        b"\xef\xbb\xbf{\"bom\":true}",
        "37c571ccb9d52b7440c9850c5ed934ef6a79209c451d578c53188d643980eb87",
        "json",
        Some("UTF-8")
    ),
];

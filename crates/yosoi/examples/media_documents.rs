//! Retain a local or HTTP file, then reopen it through the normal Archive.
use std::{env, error::Error, io};
use yosoi::{
    Archive,
    archive::FileDocumentArchiveRef,
    documents::{FileLimits, read_file},
    request,
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let input = args
        .next()
        .ok_or_else(|| io::Error::other("media_documents <file-or-http-url> <archive-root>"))?;
    if input == "--read" {
        let reference: FileDocumentArchiveRef = args
            .next()
            .ok_or_else(|| io::Error::other("missing file Archive reference"))?
            .parse()?;
        let root = args
            .next()
            .ok_or_else(|| io::Error::other("missing archive root"))?;
        let archive = Archive::open(root).await?;
        let file = archive.read(&reference).await?;
        println!(
            "Restored {} bytes; sha256 {}",
            file.byte_len(),
            file.sha256()
        );
        return Ok(());
    }
    let root = args
        .next()
        .ok_or_else(|| io::Error::other("missing archive root"))?;
    let file = if input.starts_with("http://") || input.starts_with("https://") {
        let response = request::new(input).send().await?;
        let attempt = response
            .attempts()
            .next()
            .ok_or_else(|| io::Error::other("no acquisition attempt"))?;
        if !attempt
            .status()
            .is_some_and(|status| (200..300).contains(&status))
        {
            return Err(
                io::Error::other("HTTP acquisition did not return a successful status").into(),
            );
        }
        attempt.file_document(FileLimits::default())?
    } else {
        read_file("example-file", input, FileLimits::default()).await?
    };
    let archive = Archive::open(root).await?;
    let reference = archive.write(&file).await?;
    let restored = archive.read(&reference).await?;
    println!(
        "Retained {} bytes; format {:?}; sha256 {}",
        restored.byte_len(),
        restored.metadata().detected_media_type(),
        restored.sha256()
    );
    println!("Archive reference: {reference}");
    Ok(())
}

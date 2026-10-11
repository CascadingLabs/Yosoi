use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::{sync::mpsc, time};

use super::super::DownloadOutcome;
use crate::internal::browser::error::{Result, VoidCrawlError};

pub(super) const DOWNLOAD_JS: &str = r"(async () => {
    try {
      const MAX = __MAX__;
      const ctrl = new AbortController();
      const resp = await fetch(__URL__, { credentials: 'include', signal: ctrl.signal });
      const ct = resp.headers.get('content-type');
      const cl = resp.headers.get('content-length');
      if (cl && Number(cl) > MAX) { ctrl.abort(); throw new Error('content-length ' + cl + ' exceeds limit ' + MAX); }
      let blob;
      if (resp.body && resp.body.getReader) {
        const reader = resp.body.getReader();
        const chunks = []; let total = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          total += value.byteLength;
          if (total > MAX) { ctrl.abort(); throw new Error('exceeded size limit ' + MAX + ' bytes'); }
          chunks.push(value);
        }
        blob = new Blob(chunks);
      } else {
        blob = await resp.blob();
        if (blob.size > MAX) throw new Error('exceeded size limit ' + MAX + ' bytes');
      }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (__URL__.split(/[?#]/)[0].split('/').pop()) || 'download';
      (document.body || document.documentElement).appendChild(a);
      a.click();
      return { ct, err: null };
    } catch (e) {
      return { ct: null, err: String((e && e.message) || e) };
    }
})()";

pub(super) fn strip_mime_params(mime: &str) -> String {
    mime.split(';')
        .next()
        .unwrap_or(mime)
        .trim()
        .to_ascii_lowercase()
}

pub(super) fn origin_of(url: &str) -> Option<String> {
    let (scheme, rest) = url.split_once("://")?;
    let host = rest.split(['/', '?', '#']).next()?;
    if host.is_empty() {
        return None;
    }
    Some(format!("{scheme}://{host}"))
}

pub(in crate::internal::browser::page) fn dir_entries(dir: &Path) -> HashSet<PathBuf> {
    fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|entry| entry.path())
        .collect()
}

pub(in crate::internal::browser::page) fn new_complete_files(
    dir: &Path,
    before: &HashSet<PathBuf>,
) -> Vec<(PathBuf, u64)> {
    let Ok(entries) = fs::read_dir(dir) else {
        return Vec::new();
    };
    entries
        .flatten()
        .filter_map(|entry| {
            let path = entry.path();
            if before.contains(&path)
                || path
                    .extension()
                    .is_some_and(|extension| extension == "crdownload")
            {
                return None;
            }
            match entry.metadata() {
                Ok(metadata) if metadata.is_file() && metadata.len() > 0 => {
                    Some((path, metadata.len()))
                }
                _ => None,
            }
        })
        .collect()
}

pub(in crate::internal::browser::page) fn watch_download_dir(
    dir: &Path,
) -> Result<(
    RecommendedWatcher,
    mpsc::UnboundedReceiver<notify::Result<Event>>,
)> {
    let (sender, receiver) = mpsc::unbounded_channel();
    let mut watcher = RecommendedWatcher::new(
        move |event| {
            let _ = sender.send(event);
        },
        Config::default(),
    )
    .map_err(|error| VoidCrawlError::Other(format!("watch {}: {error}", dir.display())))?;
    watcher
        .watch(dir, RecursiveMode::NonRecursive)
        .map_err(|error| VoidCrawlError::Other(format!("watch {}: {error}", dir.display())))?;
    Ok((watcher, receiver))
}

pub(in crate::internal::browser::page) async fn wait_for_new_download(
    dir: &Path,
    before: &HashSet<PathBuf>,
    max_bytes: u64,
    events: &mut mpsc::UnboundedReceiver<notify::Result<Event>>,
    timeout: Duration,
) -> Result<DownloadOutcome> {
    let wait = async {
        if let Some(outcome) = completed_download(dir, before, max_bytes)? {
            return Ok(outcome);
        }
        loop {
            match events.recv().await {
                Some(Ok(_)) => {
                    if let Some(outcome) = completed_download(dir, before, max_bytes)? {
                        return Ok(outcome);
                    }
                }
                Some(Err(error)) => {
                    return Err(VoidCrawlError::Other(format!(
                        "watch {}: {error}",
                        dir.display()
                    )));
                }
                None => {
                    return Err(VoidCrawlError::Other(format!(
                        "download watcher for {} closed",
                        dir.display()
                    )));
                }
            }
        }
    };
    time::timeout(timeout, wait)
        .await
        .map_err(|_| download_timeout(timeout))?
}

pub(in crate::internal::browser::page) fn completed_download(
    dir: &Path,
    before: &HashSet<PathBuf>,
    max_bytes: u64,
) -> Result<Option<DownloadOutcome>> {
    let files = new_complete_files(dir, before);
    if files.len() > 1 {
        let names = files
            .iter()
            .filter_map(|(path, _)| {
                path.file_name()
                    .map(|name| name.to_string_lossy().into_owned())
            })
            .collect::<Vec<_>>()
            .join(", ");
        return Err(VoidCrawlError::Other(format!(
            "ambiguous download: {} new files appeared ({names}); expected exactly one",
            files.len()
        )));
    }
    let Some((path, size)) = files.into_iter().next() else {
        return Ok(None);
    };
    if size > max_bytes {
        let _ = fs::remove_file(&path);
        return Err(VoidCrawlError::Other(format!(
            "download is {size} bytes, over the {max_bytes}-byte limit"
        )));
    }
    Ok(Some(DownloadOutcome {
        path,
        bytes: size,
        content_type: None,
    }))
}

pub(in crate::internal::browser::page) fn download_timeout(timeout: Duration) -> VoidCrawlError {
    VoidCrawlError::Timeout(format!(
        "download did not complete within {}s",
        timeout.as_secs()
    ))
}

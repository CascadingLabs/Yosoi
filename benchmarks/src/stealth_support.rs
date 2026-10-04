//! Hermetic support for CAS-374 browser fingerprint evidence.

use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use std::net::Ipv4Addr;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::{JoinHandle, JoinSet},
};
use tokio_util::sync::CancellationToken;
use void_crawl_core::Page;

mod validation;
pub use validation::{LiveSummaryParts, live_summary_parts, validate_snapshot};

pub const WEBDRIVER_DISGUISE: &str = r#"
Object.defineProperty(Object.getPrototypeOf(navigator), 'webdriver', {
    configurable: true,
    get: () => false,
});
"#;

pub const SNAPSHOT_JS: &str = r#"(async () => {
    const uaData = navigator.userAgentData;
    let highEntropy = null;
    if (uaData && uaData.getHighEntropyValues) {
        try {
            highEntropy = await uaData.getHighEntropyValues([
                'architecture', 'bitness', 'fullVersionList', 'model',
                'platformVersion', 'wow64'
            ]);
        } catch (_) {}
    }
    let permission = null;
    try {
        permission = (await navigator.permissions.query({name: 'notifications'})).state;
    } catch (_) {}
    let requestHeaders = null;
    if (location.hostname === '127.0.0.1') {
        try {
            requestHeaders = await fetch('/headers', {cache: 'no-store'}).then(response => response.json());
        } catch (_) {}
    }
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    const debug = gl && gl.getExtension('WEBGL_debug_renderer_info');
    let workerValue = {status: 'not_fixture'};
    if (location.hostname === '127.0.0.1') {
        workerValue = await new Promise(resolve => {
            const worker = new Worker('/worker.js');
            let settled = false;
            let timeoutId = null;
            const finish = value => {
                if (settled) return;
                settled = true;
                if (timeoutId !== null) clearTimeout(timeoutId);
                worker.terminate();
                resolve(value);
            };
            worker.onmessage = event => finish({status: 'ready', ...event.data});
            worker.onerror = () => finish({status: 'error'});
            timeoutId = setTimeout(() => finish({status: 'timeout'}), 5000);
        });
    }
    const frame = document.querySelector('iframe');
    let frameValue = null;
    try {
        const child = frame && frame.contentWindow && frame.contentWindow.navigator;
        if (child) {
            frameValue = {
                webdriver: child.webdriver,
                userAgent: child.userAgent,
                platform: child.platform,
                languages: Array.from(child.languages || []),
                windowChrome: !!frame.contentWindow.chrome,
            };
        }
    } catch (_) {
        frameValue = {crossOrigin: true};
    }
    const descriptor = Object.getOwnPropertyDescriptor(
        Object.getPrototypeOf(navigator), 'webdriver'
    );
    return {
        webdriver: navigator.webdriver,
        webdriverDescriptorGetter: descriptor && descriptor.get
            ? Function.prototype.toString.call(descriptor.get)
            : null,
        userAgent: navigator.userAgent,
        platform: navigator.platform,
        language: navigator.language,
        languages: Array.from(navigator.languages || []),
        hardwareConcurrency: navigator.hardwareConcurrency,
        deviceMemory: navigator.deviceMemory ?? null,
        maxTouchPoints: navigator.maxTouchPoints,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        requestHeaders,
        userAgentData: uaData ? {
            brands: Array.from(uaData.brands || []),
            mobile: uaData.mobile,
            platform: uaData.platform,
            highEntropy,
        } : null,
        viewport: {
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            screenWidth: screen.width,
            screenHeight: screen.height,
            availWidth: screen.availWidth,
            availHeight: screen.availHeight,
            devicePixelRatio: window.devicePixelRatio,
            colorDepth: screen.colorDepth,
        },
        webgl: gl ? {
            vendor: gl.getParameter(gl.VENDOR),
            renderer: gl.getParameter(gl.RENDERER),
            unmaskedVendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
            unmaskedRenderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
        } : null,
        notificationPermission: Notification.permission,
        permissionQuery: permission,
        plugins: Array.from(navigator.plugins || [], plugin => ({
            name: plugin.name,
            filename: plugin.filename,
        })),
        mimeTypesLength: navigator.mimeTypes ? navigator.mimeTypes.length : null,
        windowChrome: !!window.chrome,
        windowChromeRuntime: !!(window.chrome && window.chrome.runtime),
        automationGlobals: Object.getOwnPropertyNames(window).filter(name =>
            /webdriver|selenium|playwright|puppeteer|cdc_|wdc_|nightmare|phantom/i.test(name)
        ),
        cspInlineScriptRan: window.__cas374InlineScriptRan === true,
        frame: frameValue,
        worker: workerValue,
    };
})()"#;

pub const LIVE_READY_JS: &str = r#"new Promise(resolve => {
    const ready = () => {
        const text = document.body ? document.body.innerText : '';
        const sannyReady = Array.from(document.getElementsByTagName('tr')).some(row =>
            /WebDriver/i.test(row.innerText) && /(present|missing|pass|fail)/i.test(row.innerText)
        );
        return /"hasWebdriverTrue"\s*:\s*(true|false)/i.test(text)
            || sannyReady
            || (/FP ID:\s*[a-z0-9]/i.test(text) && !/FP ID:\s*Computing/i.test(text))
            || /Your Behavioral Score:\s*(0(?:\.\d+)?|1(?:\.0+)?)/i.test(text)
            || /"webdriverPresent"\s*:\s*"(OK|FAIL)"/i.test(text);
    };
    if (ready()) { resolve(true); return; }
    const observer = new MutationObserver(() => {
        if (ready()) { observer.disconnect(); resolve(true); }
    });
    observer.observe(document.documentElement, {subtree: true, childList: true, characterData: true});
    setTimeout(() => { observer.disconnect(); resolve(false); }, 30000);
})"#;

pub const LIVE_SUMMARY_JS: &str = r#"(() => {
    const text = document.body ? document.body.innerText : '';
    const signals = {};
    const keys = [
        'isBot', 'hasBotUserAgent', 'hasWebdriverTrue', 'hasWebdriverInFrameTrue',
        'isPlaywright', 'hasInconsistentChromeObject', 'isHeadlessChrome',
        'isWebGLInconsistent', 'hasInconsistentClientHints', 'isAutomatedWithCDP',
        'isAutomatedWithCDPInWebWorker', 'isIframeOverridden',
        'hasInconsistentWorkerValues', 'hasHighHardwareConcurrency',
        'hasHeadlessChromeDefaultScreenResolution', 'hasSuspiciousWeakSignals'
    ];
    for (const key of keys) {
        const match = text.match(new RegExp('"' + key + '"\\s*:\\s*(true|false)', 'i'));
        if (match) signals[key] = match[1].toLowerCase() === 'true';
    }
    const rows = Array.from(document.querySelectorAll('tr')).map(row => {
        const cells = Array.from(row.querySelectorAll('th,td')).map(cell => cell.innerText.trim());
        return cells.length >= 2 ? {test: cells[0], result: cells.slice(1).join(' | ')} : null;
    }).filter(row => row && /(fail|pass|present|missing)/i.test(row.result));
    const statuses = {};
    const statusKeys = [
        'puppeteerEvaluationScript', 'webdriverPresent', 'connectionRTT',
        'refMatch', 'overrideTest', 'headless', 'stealth'
    ];
    for (const key of statusKeys) {
        const match = text.match(new RegExp('["“]?' + key + '["”]?\\s*[:=]\\s*["“]?(OK|FAIL|PASS|FAILED)', 'i'));
        if (match) statuses[key] = match[1].toUpperCase();
    }
    const scores = {};
    for (const match of text.matchAll(/(\d+(?:\.\d+)?)%\s+(like headless|headless|stealth)/gi)) {
        scores[match[2].toLowerCase().replaceAll(' ', '_')] = Number(match[1]);
    }
    const behavioral = text.match(/Your Behavioral Score:\s*(0(?:\.\d+)?|1(?:\.0+)?)/i);
    if (behavioral) scores.behavioral = Number(behavioral[1]);
    const providerResources = Array.from(new Set(
        performance.getEntriesByType('resource').flatMap(entry => {
            try {
                const host = new URL(entry.name).hostname;
                return /cloudflare|captcha-delivery|datadome|kasada/i.test(host) ? [host] : [];
            } catch (_) {
                return [];
            }
        })
    )).sort();
    const challengeMarkers = [];
    for (const [name, pattern] of [
        ['cloudflare', /verify (that )?you are human|checking your browser|cloudflare ray id/i],
        ['datadome', /datadome|device check/i],
        ['kasada', /kasada|x-kpsdk/i],
        ['generic_captcha', /captcha|access denied|unusual traffic/i],
    ]) {
        if (pattern.test(text)) challengeMarkers.push(name);
    }
    return {
        title: document.title,
        signals,
        statuses,
        scores,
        providerResources,
        challengeMarkers,
        diagnosticRows: rows.slice(0, 100),
        bodyText: text
    };
})()"#;

#[derive(Debug)]
pub struct Fixture {
    pub base_url: String,
    stop: CancellationToken,
    task: JoinHandle<Result<()>>,
}

impl Fixture {
    pub async fn start() -> Result<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .await
            .context("bind CAS-374 loopback fixture")?;
        let address = listener.local_addr().context("read fixture address")?;
        let stop = CancellationToken::new();
        let task_stop = stop.clone();
        let task = tokio::spawn(async move {
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    () = task_stop.cancelled() => {
                        connections.abort_all();
                        while connections.join_next().await.is_some() {}
                        return Ok(());
                    },
                    accepted = listener.accept() => {
                        let (mut stream, peer) = accepted.context("accept fixture request")?;
                        if !peer.ip().is_loopback() { bail!("rejected non-loopback fixture peer"); }
                        let connection_stop = task_stop.clone();
                        connections.spawn(async move {
                            let mut request = vec![0_u8; 4096];
                            let read = tokio::select! {
                                () = connection_stop.cancelled() => return Ok(()),
                                read = stream.read(&mut request) => read.context("read fixture request")?,
                            };
                            let request_bytes = request
                                .get(..read)
                                .context("fixture read exceeded its buffer")?;
                            let request = String::from_utf8_lossy(request_bytes);
                            let path = request.split_whitespace().nth(1).map_or("/", |value| value);
                            let (content_type, body) = if path.starts_with("/headers") {
                                let header = |name: &str| {
                                    request.lines().find_map(|line| {
                                        let (candidate, value) = line.split_once(':')?;
                                        candidate.eq_ignore_ascii_case(name).then(|| value.trim())
                                    })
                                };
                                let selected = json!({
                                    "accept-language": header("accept-language"),
                                    "sec-ch-ua": header("sec-ch-ua"),
                                    "sec-ch-ua-arch": header("sec-ch-ua-arch"),
                                    "sec-ch-ua-bitness": header("sec-ch-ua-bitness"),
                                    "sec-ch-ua-full-version-list": header("sec-ch-ua-full-version-list"),
                                    "sec-ch-ua-mobile": header("sec-ch-ua-mobile"),
                                    "sec-ch-ua-platform": header("sec-ch-ua-platform"),
                                    "sec-ch-ua-platform-version": header("sec-ch-ua-platform-version"),
                                    "user-agent": header("user-agent"),
                                });
                                (
                                    "application/json; charset=utf-8",
                                    serde_json::to_string(&selected).context("serialize selected request headers")?,
                                )
                            } else if path.starts_with("/worker.js") {
                                (
                                    "text/javascript; charset=utf-8",
                                    "(async()=>{const data=navigator.userAgentData;let high=null;if(data&&data.getHighEntropyValues){high=await data.getHighEntropyValues(['fullVersionList','platformVersion']);}postMessage({userAgent:navigator.userAgent,platform:navigator.platform,languages:Array.from(navigator.languages||[]),hardwareConcurrency:navigator.hardwareConcurrency,deviceMemory:navigator.deviceMemory??null,userAgentData:data?{brands:Array.from(data.brands||[]),mobile:data.mobile,platform:data.platform,highEntropy:high}:null});})()".to_string(),
                                )
                            } else if path.starts_with("/frame") {
                                (
                                    "text/html; charset=utf-8",
                                    "<!doctype html><title>frame</title><p>frame</p>".to_string(),
                                )
                            } else {
                                (
                                    "text/html; charset=utf-8",
                                    "<!doctype html><title>CAS-374</title><script>window.__cas374InlineScriptRan=true</script><main>fixture</main><iframe src='/frame'></iframe>".to_string(),
                                )
                            };
                            let response = format!(
                                "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Security-Policy: default-src 'self'; script-src 'self'; worker-src 'self'\r\nAccept-CH: Sec-CH-UA-Full-Version-List, Sec-CH-UA-Platform-Version, Sec-CH-UA-Arch, Sec-CH-UA-Bitness\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                                body.len(), body
                            );
                            stream.write_all(response.as_bytes()).await.context("write fixture response")?;
                            Ok::<(), anyhow::Error>(())
                        });
                    },
                    completed = connections.join_next(), if !connections.is_empty() => {
                        completed.context("fixture connection task disappeared")???;
                    },
                }
            }
        });
        Ok(Self {
            base_url: format!("http://{address}"),
            stop,
            task,
        })
    }

    pub async fn close(self) -> Result<()> {
        self.stop.cancel();
        self.task.await.context("join fixture task")?
    }
}

pub async fn snapshot(page: &Page) -> Result<Value> {
    page.evaluate_js(SNAPSHOT_JS).await.map_err(Into::into)
}

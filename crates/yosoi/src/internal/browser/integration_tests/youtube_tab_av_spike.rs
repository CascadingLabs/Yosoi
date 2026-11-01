//! Real-site follow-up: two isolated contexts, one native browser, per-tab A/V.
use super::{Result, evaluate};
use crate::internal::browser::{BrowserSession, Page};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::{
    env,
    error::Error,
    fs, io,
    io::Write,
    path::{Path, PathBuf},
};

const CAPTURE: &str = include_str!("tab_av/youtube-capture.js");
const MEDIA: &str = r#"(()=>({title:document.title,url:location.href,body:document.body.innerText.slice(0,3000),
  buttons:Array.from(document.getElementsByTagName('button')).filter(button=>button.getClientRects().length)
    .map(button=>button.getAttribute('aria-label')||button.innerText).filter(Boolean).slice(0,100),
  videos:Array.from(document.getElementsByTagName('video')).map(video=>({paused:video.paused,
    muted:video.muted,duration:video.duration,currentTime:video.currentTime,readyState:video.readyState}))}))()"#;

async fn prepare(page: &Page, output: &Path, id: usize) -> Result<Value> {
    page.cdp().bring_to_front().await?;
    let initial = evaluate(page, MEDIA).await?;
    fs::write(
        output.join(format!("page-{id}-initial.json")),
        serde_json::to_vec_pretty(&initial)?,
    )?;
    let buttons = initial
        .get("buttons")
        .and_then(Value::as_array)
        .ok_or_else(|| io::Error::other("no page controls"))?;
    if buttons
        .iter()
        .any(|label| label.as_str() == Some("Reject all"))
    {
        page.click_by_role("button", "Reject all", 0, true).await?;
    }
    let metadata=evaluate(page,r#"new Promise((resolve,reject)=>{
      let observer;const check=()=>{const video=Array.from(document.getElementsByTagName('video')).find(v=>v.readyState>=1);
        if(video){clearTimeout(timer);observer.disconnect();resolve({paused:video.paused,muted:video.muted,duration:video.duration})}
        else if(document.body.innerText.includes("Sign in to confirm")){clearTimeout(timer);observer.disconnect();reject(Error('YouTube requires sign-in to confirm not a bot'))}};
      const timer=setTimeout(()=>{observer.disconnect();reject(Error('YouTube media element did not load'))},30000);
      observer=new MutationObserver(check);observer.observe(document,{subtree:true,childList:true,attributes:true});
      document.addEventListener('loadedmetadata',check,true);check();
    })"#).await?;
    let controls = evaluate(page, MEDIA).await?;
    fs::write(
        output.join(format!("page-{id}-controls.json")),
        serde_json::to_vec_pretty(&controls)?,
    )?;
    if metadata.get("paused") == Some(&Value::Bool(true)) {
        let labels = controls
            .get("buttons")
            .and_then(Value::as_array)
            .ok_or_else(|| io::Error::other("no player controls"))?;
        let label = labels
            .iter()
            .filter_map(Value::as_str)
            .find(|label| *label == "Play" || label.starts_with("Play ("))
            .ok_or_else(|| io::Error::other("no native Play button found"))?;
        page.click_by_role("button", label, 0, true).await?;
    }
    // Programmatic media configuration is explicit; playback was initiated by
    // trusted native input. No synthetic DOM click or external downloader.
    evaluate(page,"(()=>{for(const v of document.getElementsByTagName('video')){v.muted=false;v.volume=.8}return true})()").await?;
    evaluate(page,r#"new Promise((resolve,reject)=>{
      const video=Array.from(document.getElementsByTagName('video'))[0];
      if(!video){reject(Error('video missing'));return}
      const first=video.currentTime;let timer;
      const check=()=>{if(!video.paused&&video.readyState>=2&&video.currentTime>first+.3&&video.duration>120){
        clearTimeout(timer);video.removeEventListener('timeupdate',check);resolve({url:location.href,title:document.title,time:video.currentTime,duration:video.duration})}};
      timer=setTimeout(()=>{video.removeEventListener('timeupdate',check);reject(Error('Movie playback did not advance; possible ad, consent or player gate'))},30000);
      video.addEventListener('timeupdate',check);check();
    })"#).await
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "explicit two-YouTube-video isolated-context A/V test"]
async fn youtube_tab_av_spike() -> Result<()> {
    let origin = env::var("YOSOI_TAB_AV_ORIGIN")?;
    let output = PathBuf::from(env::var("YOSOI_TAB_AV_OUTPUT")?);
    let urls = [
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ&t=30s",
        "https://www.youtube.com/watch?v=eRsGyueVLvQ&t=60s",
    ];
    let browser = BrowserSession::builder()
        .headful()
        .viewport(640, 360)
        .window_size(960, 720)
        .arg("auto-accept-this-tab-capture")
        .launch()
        .await?;
    let result=async {
        let mut contexts=Vec::new();let mut pages=Vec::new();let mut isolation=Vec::new();
        for (id,url) in urls.into_iter().enumerate(){
            let context=browser.new_isolated_context().await?;
            let page=context.page_handle();
            page.navigate(&format!("{origin}/control")).await?;
            let before=evaluate(&page,"({storage:localStorage.getItem('yosoi-av-owner'),cookie:document.cookie})").await?;
            if before.get("storage")!=Some(&Value::Null) || before.get("cookie").and_then(Value::as_str).is_none_or(|cookie|cookie.contains("yosoi-av-owner")){
                return Err(io::Error::other("browser contexts leaked fixture state").into());
            }
            evaluate(&page,&format!("(()=>{{localStorage.setItem('yosoi-av-owner',{});document.cookie='yosoi-av-owner={id}; SameSite=Lax';return true}})()",serde_json::to_string(&id.to_string())?)).await?;
            isolation.push(json!({"id":id,"initial_state":before,"binding":context.binding(),"target":page.target_id()}));
            page.navigate(url).await?;
            let prepared=prepare(&page,&output,id).await;
            if let Err(error)=prepared{
                let diagnostic=evaluate(&page,MEDIA).await;
                fs::write(output.join(format!("page-{id}-failure.json")),format!("{diagnostic:?}"))?;
                if let Ok(png)=page.screenshot_png().await{fs::write(output.join(format!("page-{id}-failure.png")),png)?;}
                return Err(error);
            }
            pages.push(page);contexts.push(context);
        }
        let mut ready=Vec::new();
        for (id,page) in pages.iter().enumerate(){
            page.cdp().bring_to_front().await?;
            evaluate(page,&format!("({CAPTURE})({})",json!({"id":id}))).await?;
            page.click_by_role("button",&format!("Record isolated YouTube tab {id}"),0,true).await?;
            ready.push(evaluate(page,"window.__ytTabAv.ready").await?);
        }
        fs::write(output.join("capture-ready.json"),serde_json::to_vec_pretty(&ready)?)?;
        let epoch=evaluate(pages.first().ok_or_else(||io::Error::other("missing source"))?,"Date.now()+1500").await?
            .as_u64().ok_or_else(||io::Error::other("missing clock"))?;
        for page in &pages{evaluate(page,&format!("window.__ytTabAv.schedule({epoch},26000)")).await?;}
        let mut started=Vec::new();for page in &pages{started.push(evaluate(page,"window.__ytTabAv.started").await?);}
        let control=browser.new_page(&format!("{origin}/control")).await?;control.cdp().bring_to_front().await?;
        let clock=pages.first().ok_or_else(||io::Error::other("missing clock tab"))?;
        let mut phases=Vec::new();
        for (offset,id,pause) in [(6000_u64,0_usize,true),(11000,0,false),(14000,1,true),(19000,1,false)]{
            evaluate(clock,&format!("window.__ytTabAv.waitUntil({})",epoch.saturating_add(offset))).await?;
            let page=pages.get(id).ok_or_else(||io::Error::other("missing phase target"))?;
            let action=if pause{"pause"}else{"resume"};
            phases.push(json!({"id":id,"action":action,"observed":evaluate(page,&format!("window.__ytTabAv.{action}()")).await?}));
        }
        let mut results=Vec::new();
        fs::write(output.join("capture-phases.json"),serde_json::to_vec_pretty(&phases)?)?;
        for (id,page) in pages.iter().enumerate(){
            let done=evaluate(page,"window.__ytTabAv.done").await?;
            fs::write(output.join(format!("tab-{id}.json")),serde_json::to_vec_pretty(&done)?)?;
            let count=done.get("chunks").and_then(Value::as_u64).filter(|count|*count<=120)
                .ok_or_else(||io::Error::other("unbounded chunk count"))?;
            let mut file=fs::File::create(output.join(format!("tab-{id}.webm")))?;
            for chunk in 0..count{
                let encoded=evaluate(page,&format!("window.__ytTabAv.chunk({chunk})")).await?;
                let bytes=STANDARD.decode(encoded.as_str().ok_or_else(||io::Error::other("missing media chunk"))?)?;
                if chunk==0 && !bytes.starts_with(&[0x1a,0x45,0xdf,0xa3]){return Err(io::Error::other("first media chunk lacks WebM header").into());}
                file.write_all(&bytes)?;
            }
            fs::write(output.join(format!("tab-{id}.json")),serde_json::to_vec_pretty(&done)?)?;results.push(done);
        }
        let report=json!({"mode":"youtube","tabs":2,"urls":urls,"isolation":isolation,"ready":ready,
            "started":started,"phases":phases,"results":results,"scope":"one native Yosoi browser; separate disposable browser contexts; actual YouTube media; no fixture replacement"});
        fs::write(output.join("browser-report.json"),serde_json::to_vec_pretty(&report)?)?;
        drop(control);drop(pages);
        for context in contexts{let disposed=context.dispose().await;if !disposed.cleanup_complete{return Err(io::Error::other("context cleanup incomplete").into());}}
        Ok::<_,Box<dyn Error+Send+Sync>>(())
    }.await;
    let closed = browser.close().await;
    drop(browser);
    result?;
    closed?;
    Ok(())
}

// Invoked by the native Yosoi provider in an isolated, anonymous YouTube context.
(options => {
  const videos = () => Array.from(document.getElementsByTagName('video'));
  const primary = () => videos().sort((a,b) => b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0];
  const state = () => ({url:location.href,title:document.title,at:Date.now(),
    videos:videos().map(video=>({paused:video.paused,muted:video.muted,volume:video.volume,
      readyState:video.readyState,currentTime:video.currentTime,duration:video.duration,
      width:video.videoWidth,height:video.videoHeight}))});
  let resolveReady,rejectReady,resolveStarted,resolveDone,rejectDone;
  const ready=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject});ready.catch(()=>{});
  const started=new Promise(resolve=>resolveStarted=resolve);
  const done=new Promise((resolve,reject)=>{resolveDone=resolve;rejectDone=reject});done.catch(()=>{});
  const chunks=[];let stream,recorder,bytes=0,startTime,sourceInfo;
  const controller={ready,started,done,state,
    schedule(epoch,duration){
      if(!recorder)throw Error('capture not granted');
      setTimeout(()=>{
        startTime=Date.now();recorder.start(500);resolveStarted({...state(),startedAt:startTime});
        setTimeout(()=>{if(recorder.state==='recording')recorder.stop()},duration);
      },Math.max(0,epoch-Date.now()));
      return {scheduled:epoch};
    },
    pause(){videos().forEach(video=>video.pause());return state()},
    async resume(){for(const video of videos()){video.muted=false;await video.play()}return state()},
    waitUntil(epoch){return new Promise(resolve=>setTimeout(()=>resolve(state()),Math.max(0,epoch-Date.now())))},
    async chunk(index){
      const blob=chunks[index];if(!blob)throw Error('missing chunk');
      return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=reject;
        reader.onload=()=>{const data=String(reader.result);resolve(data.slice(data.lastIndexOf(',')+1))};reader.readAsDataURL(blob)});
    }
  };
  window.__ytTabAv=controller;
  const button=document.createElement('button');button.textContent=`Record isolated YouTube tab ${options.id}`;
  Object.assign(button.style,{position:'fixed',top:'8px',left:'8px',zIndex:'2147483647',padding:'14px',font:'18px system-ui'});
  document.body.append(button);
  button.onclick=async()=>{
    button.disabled=true;
    try{
      stream=await navigator.mediaDevices.getDisplayMedia({
        preferCurrentTab:true,selfBrowserSurface:'include',monitorTypeSurfaces:'exclude',surfaceSwitching:'exclude',
        video:{displaySurface:'browser',width:{ideal:640,max:640},height:{ideal:360,max:360},frameRate:{ideal:30,max:30}},
        audio:{suppressLocalAudioPlayback:true,echoCancellation:false,noiseSuppression:false,autoGainControl:false},systemAudio:'exclude'
      });
      const video=stream.getVideoTracks(),audio=stream.getAudioTracks();
      if(video.length!==1||audio.length!==1||video[0].getSettings().displaySurface!=='browser')throw Error('One browser-tab video and audio track required');
      const element=primary();if(!element)throw Error('No source video');
      let crop='whole-tab';
      if(video[0].cropTo && window.CropTarget){await video[0].cropTo(await CropTarget.fromElement(element));crop='browser Region Capture of media element'}
      sourceInfo={id:options.id,...state(),crop,video:video[0].getSettings(),audio:audio[0].getSettings()};
      const mimeType='video/webm;codecs=vp8,opus';
      recorder=new MediaRecorder(stream,{mimeType,videoBitsPerSecond:900000,audioBitsPerSecond:96000});
      recorder.ondataavailable=event=>{
        if(event.data.size){bytes+=event.data.size;chunks.push(event.data)}
        if(bytes>12*1024*1024){recorder.stop();rejectDone(Error('12 MiB recording limit exceeded'))}
      };
      recorder.onerror=event=>rejectDone(String(event.error));
      recorder.onstop=()=>{
        const result={id:options.id,startedAt:startTime,stoppedAt:Date.now(),chunks:chunks.length,bytes,
          source:sourceInfo,final:state(),focusAtStop:document.hasFocus(),visibilityAtStop:document.visibilityState};
        stream.getTracks().forEach(track=>track.stop());resolveDone(result);
      };
      button.remove();resolveReady(sourceInfo);
    }catch(error){stream?.getTracks().forEach(track=>track.stop());button.textContent=String(error);rejectReady(String(error));rejectDone(String(error))}
  };
  return {button:button.textContent,...state()};
})

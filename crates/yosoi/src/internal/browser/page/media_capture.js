// Native self-tab MediaStream and independent MediaRecorder outputs.
const operation = arguments[0], input = arguments[1];

function send(binding, token, message) {
  binding(JSON.stringify({token, ...message}));
}

if (operation === 'start_source') {
  const binding = window[input.binding];
  if (typeof binding !== 'function') throw Error('media capture binding unavailable');
  const token = input.token;
  let stream = null;
  let closed = false;
  const outputs = new Map();
  const notify = message => send(binding, token, message);
  const state = {
    startOutput(options) {
      if (!stream) throw Error('media capture stream unavailable');
      const id = options.output_id, segment = options.segment;
      const video = stream.getVideoTracks(), audio = stream.getAudioTracks();
      if (video.length !== 1 || (options.include_audio && audio.length !== 1)) {
        throw Error('media capture tracks unavailable');
      }
      const outputStream = new MediaStream(options.include_audio ? [...video, ...audio] : video);
      const codecs = options.include_audio
        ? ['video/webm;codecs=vp8,opus', 'video/webm']
        : ['video/webm;codecs=vp8', 'video/webm'];
      const mimeType = codecs.find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw Error('WebM MediaRecorder unavailable');
      const recorder = new MediaRecorder(outputStream, {
        mimeType,
        videoBitsPerSecond: 700000,
        audioBitsPerSecond: 64000,
      });
      let sequence = 0;
      let chain = Promise.resolve();
      let pendingBytes = 0;
      recorder.ondataavailable = event => {
        if (!event.data || event.data.size === 0) return;
        if (event.data.size > options.maximum_chunk_bytes
            || pendingBytes + event.data.size > options.maximum_chunk_bytes) {
          notify({kind: 'overflow', output_id: id, segment});
          if (recorder.state === 'recording') recorder.stop();
          return;
        }
        const blob = event.data;
        pendingBytes += blob.size;
        const current = sequence++;
        chain = chain.then(async () => {
          const bytes = new Uint8Array(await blob.arrayBuffer());
          let binary = '';
          for (let index = 0; index < bytes.length; index++) {
            binary += String.fromCharCode(bytes[index]);
          }
          notify({
            kind: 'chunk',
            output_id: id,
            segment,
            sequence: current,
            media_time_ms: Number.isFinite(event.timecode) ? event.timecode : null,
            mime_type: mimeType,
            data: btoa(binary),
          });
        }).catch(() => notify({kind: 'output_failure', output_id: id, segment}))
          .finally(() => { pendingBytes -= blob.size; });
      };
      recorder.onerror = () => notify({kind: 'output_failure', output_id: id, segment});
      recorder.onstop = () => {
        chain.finally(() => {
          notify({kind: 'output_stopped', output_id: id, segment});
          outputs.delete(id);
        });
      };
      outputs.set(id, recorder);
      try {
        recorder.start(500);
      } catch (error) {
        outputs.delete(id);
        throw error;
      }
      return {mime_type: mimeType};
    },
    stopOutput(id) {
      const recorder = outputs.get(id);
      if (!recorder) return false;
      if (recorder.state === 'recording') recorder.stop();
      outputs.delete(id);
      return true;
    },
    stop() {
      closed = true;
      for (const recorder of outputs.values()) {
        if (recorder.state === 'recording') recorder.stop();
      }
      outputs.clear();
      for (const track of stream?.getTracks() ?? []) track.stop();
      stream = null;
      delete window[input.binding];
    },
  };
  window[input.property] = state;
  let permissionTimer;
  const permissionTimeout = new Promise(resolve => {
    permissionTimer = setTimeout(() => {
      state.stop();
      resolve(false);
    }, input.start_timeout_ms);
  });
  const capture = navigator.mediaDevices.getDisplayMedia({
    preferCurrentTab: true,
    selfBrowserSurface: 'include',
    monitorTypeSurfaces: 'exclude',
    surfaceSwitching: 'exclude',
    video: {
      displaySurface: 'browser',
      frameRate: {ideal: input.frames_per_second, max: input.frames_per_second},
    },
    audio: input.include_audio ? {suppressLocalAudioPlayback: true} : false,
    systemAudio: 'exclude',
  }).then(captured => {
    if (closed) {
      for (const track of captured.getTracks()) track.stop();
      return false;
    }
    stream = captured;
    const video = stream.getVideoTracks(), audio = stream.getAudioTracks();
    if (video.length !== 1 || (input.include_audio && audio.length !== 1)
        || (!input.include_audio && audio.length !== 0)) {
      state.stop();
      throw Error('self-tab capture returned unexpected tracks');
    }
    for (const track of stream.getTracks()) {
      track.addEventListener('ended', () => notify({kind: 'stream_ended'}), {once: true});
    }
    return true;
  });
  return Promise.race([capture, permissionTimeout]).finally(() => {
    clearTimeout(permissionTimer);
  });
}

if (operation === 'start_output') {
  const state = window[input.property];
  if (!state) throw Error('media capture source unavailable');
  return state.startOutput(input);
}

if (operation === 'stop_output') {
  const state = window[input.property];
  return state ? state.stopOutput(input.output_id) : false;
}

if (operation === 'stop_source') {
  const state = window[input.property];
  if (state) state.stop();
  delete window[input.property];
  delete window[input.binding];
  return true;
}

throw Error('unknown native media capture operation');
